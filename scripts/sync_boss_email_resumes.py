"""Incrementally sync BOSS email resumes from the legacy DB into the preview DB."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.db.engine import run_migrations
from app.domain.conversation.matching import ConversationMatch, resolve_unique_conversation
from app.domain.conversation.repository import ConversationRepository
from app.domain.scoring.engine import POSITION_SCORING_VERSION, score_resume_for_profile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_INSERT_SQL = """
INSERT INTO resumes (
  id, payload, phone_key, job_type, match_score, updated_at,
  parsed_name, linked_session_id, linked_platform, linked_owner,
  linked_platform_conversation_id, source_artifact_id
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(id) DO NOTHING
"""
_UPDATE_SQL = """
UPDATE resumes
SET payload = ?, job_type = ?, match_score = ?, updated_at = ?
WHERE id = ?
"""
_EMAIL_POSITION_PATTERN = re.compile(r"【([^】]+)】")
_JOB_TITLE_RULES: tuple[tuple[str, str], ...] = (
    ("ai智能体解决方案负责人", "AI智能体解决方案负责人"),
    ("ai产品经理", "AI产品经理"),
    ("投资交易策略研究员", "投资交易策略研究员（量化与市场情绪方向）"),
    ("企业内容运营负责人", "运营A"),
    ("外部财务产品顾问", "外部财务产品顾问"),
    ("ai应用开发实习生", "AI应用开发实习生"),
    ("ai应用开发工程师", "AI应用开发工程师"),
    ("应用技术经理", "应用技术经理（工业涂料领域）"),
    ("销售工程师石油钻井泥浆膨润土", "销售工程师（石油钻井泥浆膨润土）_湖州"),
    ("膨润土销售人员", "膨润土销售人员"),
    ("销售管培生", "销售管培生"),
    ("国际业务管培生", "国际业务管培生"),
    ("人力资源管培生", "人力资源管培生"),
    ("hrbp", "HRBP"),
    ("电气工程师", "电气工程师"),
)


@dataclass(frozen=True)
class BossEmailSyncConfig:
    """Configuration for one insert-only BOSS email resume sync."""

    source_db: Path
    source_upload_dir: Path
    target_db: Path
    target_upload_dir: Path
    limit: int | None = None
    apply: bool = False
    yes: bool = False
    backup: bool = False
    repair_existing: bool = False


def run_sync(
    config: BossEmailSyncConfig,
    *,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Copy missing BOSS rows and PDFs without modifying existing target rows."""

    _validate_config(config)
    sync_time = now_iso or datetime.now(UTC).isoformat()
    report = _empty_report(config, sync_time)
    source_rows = _load_source_rows(config.source_db)
    target_records = _target_records(config.target_db)
    conversation_repository = (
        ConversationRepository(config.target_db, migrate=False)
        if config.target_db.exists()
        else None
    )
    prepared: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []

    for row in source_rows:
        payload = _decode_payload(row)
        if _source_platform(payload) != "boss":
            report["skippedNonBoss"] += 1
            continue
        report["sourceBoss"] += 1
        resume_id = str(row["id"])
        existing = target_records.get(resume_id)
        existing_payload: dict[str, Any] | None = None
        if existing is not None:
            report["skippedExisting"] += 1
            existing_payload = _decode_payload(existing)
            if not (
                config.repair_existing
                and existing_payload.get("bossEmailSyncedAt")
            ):
                continue
        target_job = infer_boss_email_job_type(payload)
        position_evidence = _email_position_title(payload)
        if not target_job:
            report["unmappedJobTitle"] += 1
            if len(report["unmappedJobTitleSamples"]) < 10:
                report["unmappedJobTitleSamples"].append(
                    {"id": resume_id, "fileName": payload.get("fileName", "")}
                )
            continue
        if existing is not None:
            assert existing_payload is not None
            current_job = str(existing["job_type"] or "")
            if current_job != target_job:
                repaired_payload, repaired_score = _apply_job_assignment(
                    existing_payload,
                    original_job=current_job,
                    target_job=target_job,
                    position_evidence=position_evidence,
                    sync_time=sync_time,
                    corrected=True,
                )
                repairs.append(
                    {
                        "id": resume_id,
                        "payload": repaired_payload,
                        "job_type": target_job,
                        "score": repaired_score,
                    }
                )
            continue
        if config.limit is not None and len(prepared) >= config.limit:
            report["skippedLimit"] += 1
            continue

        source_pdf = _resolve_source_pdf(
            resume_id,
            payload,
            config.source_upload_dir,
        )
        if source_pdf is None or not source_pdf.is_file():
            report["missingPdf"] += 1
            if len(report["missingPdfSamples"]) < 10:
                report["missingPdfSamples"].append(resume_id)
            continue
        if not _is_pdf(source_pdf):
            report["invalidPdf"] += 1
            if len(report["invalidPdfSamples"]) < 10:
                report["invalidPdfSamples"].append(resume_id)
            continue

        report["pdfExisting"] += 1
        target_pdf = (
            config.target_upload_dir
            / "boss-email"
            / f"{resume_id}{source_pdf.suffix.lower() or '.pdf'}"
        )
        rewritten_payload = _rewrite_payload(payload, source_pdf, target_pdf, sync_time)
        rewritten_payload, score = _apply_job_assignment(
            rewritten_payload,
            original_job=str(row["job_type"] or ""),
            target_job=target_job,
            position_evidence=position_evidence,
            sync_time=sync_time,
            corrected=str(row["job_type"] or "") != target_job,
        )
        link = _match_conversation(
            conversation_repository,
            payload=rewritten_payload,
            target_job=target_job,
        )
        if link.session is not None:
            report["linkedUnique"] += 1
        elif link.reason == "conversation_ambiguous":
            report["linkAmbiguous"] += 1
        else:
            report["linkMissing"] += 1
        prepared.append(
            {
                "row": row,
                "payload": rewritten_payload,
                "job_type": target_job,
                "score": score,
                "source_pdf": source_pdf,
                "target_pdf": target_pdf,
                "link": link,
            }
        )

    report["wouldImport"] = len(prepared)
    report["wouldRepair"] = len(repairs)
    if not config.apply or (not prepared and not repairs):
        return report
    if not config.yes:
        raise RuntimeError("apply_requires_yes")

    if config.backup:
        backup_path = _backup_target(config.target_db)
        report["targetBackupPath"] = str(backup_path)

    run_migrations(config.target_db)
    if prepared:
        target_folder = config.target_upload_dir / "boss-email"
        target_folder.mkdir(parents=True, exist_ok=True)
        for item in prepared:
            target_pdf = item["target_pdf"]
            shutil.copy2(item["source_pdf"], target_pdf)
            report["pdfCopied"] += 1

    with closing(sqlite3.connect(config.target_db, timeout=30)) as connection:
        connection.execute("PRAGMA busy_timeout = 30000")
        for item in prepared:
            row = item["row"]
            payload = item["payload"]
            link = item["link"]
            linked_session = link.session
            cursor = connection.execute(
                _INSERT_SQL,
                (
                    row["id"],
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    row["phone_key"],
                    item["job_type"],
                    item["score"],
                    sync_time,
                    _first_text(payload.get("name"), payload.get("candidateName")),
                    linked_session.id if linked_session else "",
                    linked_session.platform if linked_session else "boss",
                    linked_session.owner if linked_session else _source_owner(payload),
                    linked_session.platform_conversation_id if linked_session else "",
                    "",
                ),
            )
            if cursor.rowcount:
                report["imported"] += 1
            else:
                report["skippedRace"] += 1
        for item in repairs:
            cursor = connection.execute(
                _UPDATE_SQL,
                (
                    json.dumps(item["payload"], ensure_ascii=False, sort_keys=True),
                    item["job_type"],
                    item["score"],
                    sync_time,
                    item["id"],
                ),
            )
            report["repaired"] += cursor.rowcount
        connection.commit()
    return report


def _validate_config(config: BossEmailSyncConfig) -> None:
    if not config.source_db.is_file():
        raise FileNotFoundError(f"source_db_not_found: {config.source_db}")
    if not config.source_upload_dir.is_dir():
        raise FileNotFoundError(
            f"source_upload_dir_not_found: {config.source_upload_dir}"
        )
    if config.source_db.resolve() == config.target_db.resolve():
        raise ValueError("source_and_target_db_must_differ")
    if config.limit is not None and config.limit < 1:
        raise ValueError("limit_must_be_positive")


def _empty_report(config: BossEmailSyncConfig, sync_time: str) -> dict[str, Any]:
    return {
        "dryRun": not config.apply,
        "sourceDb": str(config.source_db),
        "targetDb": str(config.target_db),
        "syncTime": sync_time,
        "sourceBoss": 0,
        "wouldImport": 0,
        "wouldRepair": 0,
        "imported": 0,
        "repaired": 0,
        "linkedUnique": 0,
        "linkAmbiguous": 0,
        "linkMissing": 0,
        "skippedNonBoss": 0,
        "skippedExisting": 0,
        "skippedLimit": 0,
        "skippedRace": 0,
        "pdfExisting": 0,
        "pdfCopied": 0,
        "missingPdf": 0,
        "invalidPdf": 0,
        "unmappedJobTitle": 0,
        "missingPdfSamples": [],
        "invalidPdfSamples": [],
        "unmappedJobTitleSamples": [],
        "targetBackupPath": "",
    }


def _load_source_rows(database: Path) -> list[sqlite3.Row]:
    uri = database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as connection:
        connection.row_factory = sqlite3.Row
        columns = {row[1] for row in connection.execute("PRAGMA table_info(resumes)")}
        required = {"id", "payload", "phone_key", "job_type", "match_score", "updated_at"}
        missing = sorted(required - columns)
        if missing:
            raise RuntimeError(f"source_resumes_schema_missing_columns: {missing}")
        return list(connection.execute("SELECT * FROM resumes ORDER BY updated_at DESC"))


def _target_records(database: Path) -> dict[str, sqlite3.Row]:
    if not database.exists():
        return {}
    try:
        uri = database.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=30)) as connection:
            connection.row_factory = sqlite3.Row
            return {
                str(row["id"]): row
                for row in connection.execute("SELECT * FROM resumes")
            }
    except sqlite3.Error:
        return {}


def _decode_payload(row: sqlite3.Row) -> dict[str, Any]:
    try:
        value = json.loads(row["payload"])
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _source_platform(payload: dict[str, Any]) -> str:
    return _first_text(
        payload.get("platform"),
        payload.get("sourcePlatform"),
        payload.get("source"),
    ).lower()


def _source_owner(payload: dict[str, Any]) -> str:
    return _first_text(
        payload.get("accountName"),
        payload.get("sourceName"),
        payload.get("owner"),
    )


def _match_conversation(
    repository: ConversationRepository | None,
    *,
    payload: dict[str, Any],
    target_job: str,
) -> ConversationMatch:
    if repository is None:
        return ConversationMatch(None, "none", "conversation_not_linked", 0)
    return resolve_unique_conversation(
        repository,
        candidate_name=_first_text(payload.get("name"), payload.get("candidateName")),
        position=target_job,
        platform="boss",
        owner=_source_owner(payload),
    )


def infer_boss_email_job_type(payload: dict[str, Any]) -> str:
    """Return the canonical resume-library job from the original BOSS title."""

    compact = re.sub(
        r"[^0-9A-Za-z\u4e00-\u9fff]+",
        "",
        _email_position_title(payload),
    ).lower()
    for keyword, job_type in _JOB_TITLE_RULES:
        if keyword in compact:
            return job_type
    return ""


def _email_position_title(payload: dict[str, Any]) -> str:
    file_name = str(payload.get("fileName") or "")
    match = _EMAIL_POSITION_PATTERN.search(file_name)
    return match.group(1).strip() if match else ""


def _apply_job_assignment(
    payload: dict[str, Any],
    *,
    original_job: str,
    target_job: str,
    position_evidence: str,
    sync_time: str,
    corrected: bool,
) -> tuple[dict[str, Any], int]:
    updated = dict(payload)
    updated.setdefault("bossEmailOriginalJobType", original_job)
    updated["bossEmailPositionEvidence"] = position_evidence
    updated["jobType"] = target_job
    updated["appliedPosition"] = target_job
    result = score_resume_for_profile(updated, target_job)
    score = int(result["score"])
    updated["matchScore"] = score
    updated["jdMatch"] = result
    updated["scoreBreakdown"] = result
    updated["scoringVersion"] = POSITION_SCORING_VERSION
    if corrected:
        updated["bossEmailJobCorrectedAt"] = sync_time
    return updated, score


def _resolve_source_pdf(
    resume_id: str,
    payload: dict[str, Any],
    source_upload_dir: Path,
) -> Path | None:
    for key in ("pdfPath", "pdf_path", "filePath", "file_path", "sourceFilePath"):
        value = payload.get(key)
        if not value:
            continue
        path = Path(str(value))
        if path.is_absolute():
            return path
        candidate = source_upload_dir / path.name
        return candidate if candidate.exists() else path
    fallback = source_upload_dir / f"{resume_id}.pdf"
    return fallback if fallback.exists() else None


def _is_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def _rewrite_payload(
    payload: dict[str, Any],
    source_pdf: Path,
    target_pdf: Path,
    sync_time: str,
) -> dict[str, Any]:
    updated = dict(payload)
    original = _first_text(
        payload.get("pdfPath"),
        payload.get("filePath"),
        source_pdf,
    )
    updated.setdefault("legacyPdfPath", original)
    updated["pdfPath"] = str(target_pdf)
    updated["filePath"] = str(target_pdf)
    updated["hasPdf"] = True
    updated["bossEmailSyncedAt"] = sync_time
    return updated


def _first_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _backup_target(target_db: Path) -> Path:
    if not target_db.is_file():
        raise FileNotFoundError(f"target_db_not_found_for_backup: {target_db}")
    backup_dir = target_db.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"resumes_before_boss_email_sync_{timestamp}.sqlite"
    source_uri = target_db.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True, timeout=30)) as source:
        with closing(sqlite3.connect(backup_path)) as destination:
            source.backup(destination)
    return backup_path


def _default_config(args: argparse.Namespace) -> BossEmailSyncConfig:
    source_db = Path(args.source_db)
    source_upload_dir = (
        Path(args.source_upload_dir)
        if args.source_upload_dir
        else source_db.parent / "uploads"
    )
    target_db = Path(args.target_db) if args.target_db else PROJECT_ROOT / "data" / "resumes.sqlite"
    target_upload_dir = (
        Path(args.target_upload_dir)
        if args.target_upload_dir
        else PROJECT_ROOT / "data" / "uploads"
    )
    return BossEmailSyncConfig(
        source_db=source_db,
        source_upload_dir=source_upload_dir,
        target_db=target_db,
        target_upload_dir=target_upload_dir,
        limit=args.limit,
        apply=args.apply,
        yes=args.yes,
        backup=args.backup,
        repair_existing=args.repair_existing,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--source-upload-dir", default="")
    parser.add_argument("--target-db", default="")
    parser.add_argument("--target-upload-dir", default="")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--repair-existing", action="store_true")
    parser.add_argument("--log-file", default="")
    args = parser.parse_args()
    config = _default_config(args)
    report = run_sync(config)
    output = json.dumps(report, ensure_ascii=False, sort_keys=True)
    print(output)
    if args.log_file:
        log_path = Path(args.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(output + "\n")


if __name__ == "__main__":
    main()
