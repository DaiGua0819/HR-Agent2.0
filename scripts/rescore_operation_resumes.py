"""Rescore operation A/B resumes imported since a given date."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.resume.job_types import OPERATION_A, OPERATION_B, canonical_resume_job_type
from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository
from app.domain.scoring.service import ScoringService
from app.settings import load_settings


@dataclass(frozen=True)
class RescoreConfig:
    """Configuration for an operation resume rescore run."""

    database_path: Path
    since: str = "2026-06-25"
    until: str = ""
    apply: bool = False
    limit: int | None = None


def rescore_operation_resumes(config: RescoreConfig) -> dict[str, Any]:
    """Rescore operation A/B resumes in the date window."""

    repository = ResumeRepository(config.database_path)
    service = ScoringService(repository)
    since = _date_key(config.since)
    until = _date_key(config.until) or date.today().isoformat()
    report: dict[str, Any] = {
        "dryRun": not config.apply,
        "databasePath": str(config.database_path),
        "since": since,
        "until": until,
        "matched": 0,
        "updated": 0,
        "byJob": {},
        "items": [],
    }
    for record in repository.iter_resumes():
        if config.limit is not None and report["matched"] >= config.limit:
            break
        job = canonical_resume_job_type(record.job_type or record.payload.get("jobType"))
        if job not in {OPERATION_A, OPERATION_B}:
            continue
        updated_date = _date_key(record.updated_at or record.payload.get("updatedAt"))
        if not updated_date or updated_date < since or updated_date > until:
            continue
        resume = Resume.from_record(record)
        result = service.score_resume(resume)
        report["matched"] += 1
        report["byJob"][job] = int(report["byJob"].get(job, 0)) + 1
        item = {
            "resumeId": record.id,
            "jobType": job,
            "oldScore": record.match_score,
            "newScore": result["score"],
            "level": result["level"],
            "updatedAt": record.updated_at,
        }
        report["items"].append(item)
        if config.apply:
            repository.update_score(record.id, int(result["score"]))
            report["updated"] += 1
    return report


def _date_key(value: object) -> str:
    text = str(value or "").strip().replace("/", "-")
    if not text:
        return ""
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return ""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="")
    parser.add_argument("--since", default="2026-06-25")
    parser.add_argument("--until", default="")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    database = Path(args.database) if args.database else load_settings().resolved_database_path
    report = rescore_operation_resumes(
        RescoreConfig(
            database_path=database,
            since=args.since,
            until=args.until,
            apply=args.apply,
            limit=args.limit,
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
