"""Rescore B2B AI product manager resumes and build an auditable recommendation report."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) in sys.path:
    sys.path.remove(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.text import clean_text  # noqa: E402
from app.domain.resume.job_types import (  # noqa: E402
    AI_PRODUCT_MANAGER,
    canonical_resume_job_type,
)
from app.domain.resume.models import Resume, ResumeRecord  # noqa: E402
from app.domain.resume.repository import ResumeRepository  # noqa: E402
from app.domain.scoring.engine import POSITION_SCORING_VERSION  # noqa: E402
from app.domain.scoring.service import ScoringService  # noqa: E402

_DEFAULT_RECOMMENDATION_COUNT = 20
_SIMILAR_IDENTITY_THRESHOLD = 0.86
_ANONYMOUS_CANDIDATE_NAME = re.compile(r"^[\u4e00-\u9fff]{1,2}(?:先生|女士|同学)$")
_INVALID_CANDIDATE_NAME_MARKERS = (
    "应聘职位",
    "求职意向",
    "期望职位",
    "未命名候选人",
)


def build_b2b_ai_pm_report(
    database_path: str | Path,
    *,
    latest_count: int = 2,
    recommendation_count: int = _DEFAULT_RECOMMENDATION_COUNT,
) -> dict[str, Any]:
    """Score all AI product manager records without writing to the database."""

    database = Path(database_path)
    repository = ResumeRepository(database, read_only=True)
    scoring = ScoringService(repository)
    records = [
        record
        for record in repository.iter_resumes()
        if canonical_resume_job_type(record.job_type) == AI_PRODUCT_MANAGER
    ]
    scored = [_score_record(record, scoring) for record in records]
    newest = scored[: max(0, latest_count)]
    ranked = sorted(scored, key=_recommendation_sort_key)
    recommendations = _deduplicate_recommendations(ranked)[: max(0, recommendation_count)]
    public_scored = [_public_row(item) for item in scored]
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "databasePath": str(database.resolve()),
        "scoringVersion": POSITION_SCORING_VERSION,
        "sourceCount": len(records),
        "latestCandidates": [_public_row(item) for item in newest],
        "recommendations": [_public_row(item) for item in recommendations],
        "scoredCandidates": public_scored,
    }


def apply_latest_scores(
    database_path: str | Path,
    report: dict[str, Any],
    backup_dir: str | Path,
) -> dict[str, Any]:
    """Back up SQLite and persist only the IDs frozen in ``latestCandidates``."""

    database = Path(database_path)
    if not database.is_file():
        raise FileNotFoundError(database)
    backup_root = Path(backup_dir)
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_root / f"resumes_before_b2b_ai_pm_rescore_{timestamp}.sqlite"
    _backup_sqlite(database, backup_path)

    repository = ResumeRepository(database)
    updated: list[dict[str, Any]] = []
    for item in report.get("latestCandidates", []):
        resume_id = clean_text(item.get("resumeId"))
        current = repository.get(resume_id)
        if current is None:
            raise RuntimeError(f"resume_not_found:{resume_id}")
        if canonical_resume_job_type(current.job_type) != AI_PRODUCT_MANAGER:
            raise RuntimeError(f"resume_job_changed:{resume_id}")
        score = int(item["newScore"])
        stored = repository.update_score(resume_id, score)
        if stored is None:
            raise RuntimeError(f"resume_update_failed:{resume_id}")
        updated.append(
            {
                "resumeId": resume_id,
                "candidateName": item.get("candidateName") or "",
                "oldScore": item.get("oldScore"),
                "newScore": score,
            }
        )
    return {"backupPath": str(backup_path.resolve()), "updatedLatest": updated}


def _score_record(record: ResumeRecord, scoring: ScoringService) -> dict[str, Any]:
    resume = Resume.from_record(record)
    result = scoring.score_resume(resume)
    raw = result["raw"]
    candidate_name = _candidate_name(record, resume)
    phone_key = clean_text(record.phone_key or resume.phone_key or resume.phone)
    file_hash = _payload_value(
        record.payload,
        "fileHash",
        "file_hash",
        "sha256",
        "sourceHash",
        "source_hash",
    )
    must_labels = [item["label"] for item in result["evidence"]["must"]]
    risk_labels = [item["label"] for item in result["evidence"]["risks"]]
    missing_gates = list(raw["missingHardGates"])
    return {
        "resumeId": record.id,
        "candidateName": candidate_name,
        "jobType": AI_PRODUCT_MANAGER,
        "platform": clean_text(
            record.linked_platform
            or resume.source_platform
            or _payload_value(record.payload, "sourcePlatform", "platform")
        ),
        "owner": clean_text(
            record.linked_owner
            or resume.source_owner
            or _payload_value(record.payload, "owner", "sourceOwner", "source_owner")
        ),
        "oldScore": record.match_score,
        "newScore": int(result["score"]),
        "level": result["level"],
        "hardGates": raw["hardGates"],
        "missingHardGates": missing_gates,
        "hardGateCap": raw["hardGateCap"],
        "must": result["evidence"]["must"],
        "bonus": result["evidence"]["bonus"],
        "risks": result["evidence"]["risks"],
        "updatedAt": record.updated_at,
        "recommendationReason": _recommendation_reason(
            missing_gates=missing_gates,
            must_labels=must_labels,
            risk_labels=risk_labels,
        ),
        "_phoneKey": phone_key,
        "_fileHash": clean_text(file_hash).lower(),
        "_identityName": _normalize_identity(candidate_name),
        "_identityText": _identity_text(record.payload),
        "_mustCount": len(must_labels),
        "_riskCount": len(risk_labels),
    }


def _recommendation_reason(
    *,
    missing_gates: list[str],
    must_labels: list[str],
    risk_labels: list[str],
) -> str:
    gate_text = (
        "通过B2B销售理解和企业级产品经验硬门槛"
        if not missing_gates
        else f"待复核：缺少{'、'.join(missing_gates)}"
    )
    evidence = "、".join(must_labels[:3]) or "核心能力证据较少"
    risk = f"；风险：{'、'.join(risk_labels)}" if risk_labels else ""
    return f"{gate_text}；核心证据：{evidence}{risk}"


def _recommendation_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -int(not item["missingHardGates"]),
        -int(item["newScore"]),
        -int(item["_mustCount"]),
        int(item["_riskCount"]),
        -_timestamp(item["updatedAt"]),
    )


def _deduplicate_recommendations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_phones: set[str] = set()
    seen_hashes: set[str] = set()
    for row in rows:
        phone = row["_phoneKey"]
        file_hash = row["_fileHash"]
        if phone and phone in seen_phones:
            continue
        if file_hash and file_hash in seen_hashes:
            continue
        if any(_same_candidate(row, current) for current in selected):
            continue
        selected.append(row)
        if phone:
            seen_phones.add(phone)
        if file_hash:
            seen_hashes.add(file_hash)
    return selected


def _same_candidate(left: dict[str, Any], right: dict[str, Any]) -> bool:
    name = left["_identityName"]
    if not name or name != right["_identityName"]:
        return False
    left_text = left["_identityText"]
    right_text = right["_identityText"]
    if len(left_text) < 200 or len(right_text) < 200:
        return False
    return SequenceMatcher(None, left_text, right_text).ratio() >= _SIMILAR_IDENTITY_THRESHOLD


def _candidate_name(record: ResumeRecord, resume: Resume) -> str:
    candidates = (
        _payload_value(record.payload, "candidateNameFromPlatform"),
        record.parsed_name,
        resume.name,
        _payload_value(record.payload, "name", "candidateName", "resumeName"),
    )
    for candidate in candidates:
        if _is_specific_candidate_name(candidate):
            return clean_text(candidate)
    return clean_text(next((item for item in candidates if clean_text(item)), "未命名候选人"))


def _is_specific_candidate_name(value: object) -> bool:
    name = clean_text(value)
    if not name or len(name) > 20:
        return False
    if _ANONYMOUS_CANDIDATE_NAME.fullmatch(name):
        return False
    return not any(marker in name for marker in _INVALID_CANDIDATE_NAME_MARKERS)


def _payload_value(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _identity_text(payload: dict[str, Any]) -> str:
    value = _payload_value(payload, "rawText", "text", "resumeText", "content")
    return _normalize_identity(value)[:12000]


def _normalize_identity(value: object) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", clean_text(value).lower())


def _timestamp(value: object) -> float:
    text = clean_text(value)
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _public_row(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if not key.startswith("_")}


def _backup_sqlite(source_path: Path, backup_path: Path) -> None:
    source = sqlite3.connect(source_path)
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply-latest", type=int, default=0)
    parser.add_argument("--recommendations", type=int, default=_DEFAULT_RECOMMENDATION_COUNT)
    parser.add_argument("--backup-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.apply_latest < 0:
        raise SystemExit("--apply-latest must be >= 0")
    report = build_b2b_ai_pm_report(
        args.database,
        latest_count=args.apply_latest or 2,
        recommendation_count=args.recommendations,
    )
    if args.apply_latest:
        backup_dir = args.backup_dir or args.database.parent / "backups"
        report.update(apply_latest_scores(args.database, report, backup_dir))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "sourceCount": report["sourceCount"],
                "latestCandidates": report["latestCandidates"],
                "recommendationCount": len(report["recommendations"]),
                "backupPath": report.get("backupPath", ""),
                "reportPath": str(args.report.resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
