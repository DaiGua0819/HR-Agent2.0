"""Repair parsed fullstack resume artifacts created with truncated platform titles."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.db.engine import connect
from app.domain.resume.job_types import FULLSTACK_ENGINEER, canonical_resume_job_type
from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository


def backfill_fullstack_resume_artifacts(
    database_path: str | Path,
    *,
    apply: bool = False,
    limit: int = 100,
    backup_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Repair canonical job fields and missing scores for parsed fullstack artifacts."""

    database = Path(database_path)
    candidates = _find_candidates(database, limit=max(0, int(limit)))
    report: dict[str, Any] = {
        "databasePath": str(database),
        "apply": bool(apply),
        "candidates": len(candidates),
        "repaired": 0,
        "failures": [],
        "backupPath": "",
        "items": [],
    }
    for row in candidates:
        report["items"].append(
            {
                "artifactId": row["artifact_id"],
                "resumeId": row["resume_id"],
                "oldArtifactPosition": row["artifact_position"],
                "oldResumeJobType": row["resume_job_type"],
                "oldScore": row["match_score"],
            }
        )
    if not apply or not candidates:
        return report

    destination = Path(backup_dir) if backup_dir else database.parent / "backups"
    report["backupPath"] = str(_backup_database(database, destination))
    repository = ResumeRepository.for_initialized_database(database)
    for item, row in zip(report["items"], candidates, strict=True):
        try:
            record = repository.get(str(row["resume_id"]))
            if record is None:
                raise RuntimeError("linked_resume_missing")
            resume = Resume.from_record(record)
            payload = dict(resume.payload)
            payload["applied_position"] = FULLSTACK_ENGINEER
            repaired = resume.model_copy(
                update={
                    "applied_position": FULLSTACK_ENGINEER,
                    "job_type": FULLSTACK_ENGINEER,
                    "payload": payload,
                    "updated_at": _now_iso(),
                }
            )
            with connect(database) as connection:
                connection.execute("BEGIN IMMEDIATE")
                stored = repository.save_in_transaction(repaired, connection)
                connection.execute(
                    """
                    UPDATE resume_artifacts
                    SET position = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (FULLSTACK_ENGINEER, _now_iso(), row["artifact_id"]),
                )
                connection.commit()
            item["newArtifactPosition"] = FULLSTACK_ENGINEER
            item["newResumeJobType"] = stored.job_type
            item["newScore"] = stored.match_score
            report["repaired"] += 1
        except Exception as error:
            report["failures"].append(
                {
                    "artifactId": row["artifact_id"],
                    "resumeId": row["resume_id"],
                    "error": f"{type(error).__name__}: {error}",
                }
            )
    return report


def _find_candidates(database: Path, *, limit: int) -> list[dict[str, Any]]:
    if limit == 0:
        return []
    with connect(database, read_only=True) as connection:
        rows = connection.execute(
            """
            SELECT
              a.id AS artifact_id,
              a.position AS artifact_position,
              a.resume_id AS resume_id,
              r.job_type AS resume_job_type,
              r.match_score AS match_score,
              r.payload AS payload
            FROM resume_artifacts AS a
            JOIN resumes AS r ON r.id = a.resume_id
            WHERE a.parse_status = 'parsed' AND a.resume_id <> ''
            ORDER BY a.updated_at DESC
            """
        ).fetchall()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        payload = _json_object(row["payload"])
        positions = (
            row["artifact_position"],
            row["resume_job_type"],
            payload.get("applied_position"),
            payload.get("jobType"),
        )
        if not any(canonical_resume_job_type(value) == FULLSTACK_ENGINEER for value in positions):
            continue
        if (
            row["artifact_position"] == FULLSTACK_ENGINEER
            and row["resume_job_type"] == FULLSTACK_ENGINEER
            and payload.get("applied_position") == FULLSTACK_ENGINEER
            and row["match_score"] is not None
        ):
            continue
        candidates.append(dict(row))
        if len(candidates) >= limit:
            break
    return candidates


def _backup_database(database: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%SZ")
    backup_path = backup_dir / f"resumes-before-fullstack-backfill-{timestamp}.sqlite"
    with sqlite3.connect(database) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)
    return backup_path


def _json_object(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair parsed fullstack artifacts with canonical job fields and scores."
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--backup-dir")
    args = parser.parse_args()
    report = backfill_fullstack_resume_artifacts(
        args.database,
        apply=args.apply,
        limit=args.limit,
        backup_dir=args.backup_dir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
