"""Repair stored resume names using authoritative platform and file-name evidence."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta, timezone
from datetime import date as date_type
from pathlib import Path
from typing import Any

from app.db.engine import connect
from app.domain.resume.name_parser import (
    choose_resume_name,
    is_anonymous_resume_name,
    is_trustworthy_resume_name,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
_ARTIFACT_PLATFORMS = {"job51", "zhilian"}


def repair_resume_names(
    database_path: str | Path,
    *,
    date: str,
    apply: bool = False,
    backup_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Preview or repair bad names for one Beijing calendar date."""

    database = Path(database_path)
    target_date = date_type.fromisoformat(date)
    rows = _load_rows(database)
    artifacts_by_id, artifacts_by_resume = _load_artifacts(database)
    items: list[dict[str, Any]] = []
    scanned = 0

    for row in rows:
        if _beijing_date(str(row["updated_at"] or "")) != target_date:
            continue
        scanned += 1
        payload = _json_object(row["payload"])
        artifact = artifacts_by_id.get(str(row["source_artifact_id"] or ""))
        if artifact is None:
            artifact = artifacts_by_resume.get(str(row["id"]))
        platform = _first_text(
            artifact["platform"] if artifact is not None else "",
            row["linked_platform"],
            payload.get("platform"),
            payload.get("sourcePlatform"),
        ).casefold()
        current_name = _first_text(
            row["parsed_name"],
            payload.get("name"),
            payload.get("candidateName"),
        )
        platform_name = _first_text(
            artifact["candidate_name_from_platform"] if artifact is not None else "",
            payload.get("candidateNameFromPlatform"),
        )
        file_name = _first_text(
            artifact["file_path"] if artifact is not None else "",
            payload.get("fileName"),
            payload.get("filePath"),
            payload.get("pdfPath"),
            payload.get("resumePath"),
            payload.get("path"),
        )
        replacement = _replacement_name(
            platform=platform,
            current_name=current_name,
            platform_name=platform_name,
            file_name=file_name,
        )
        if not replacement or replacement == current_name:
            continue
        items.append(
            {
                "resumeId": str(row["id"]),
                "artifactId": str(artifact["id"]) if artifact is not None else "",
                "platform": platform,
                "oldName": current_name,
                "newName": replacement,
                "updatedAt": str(row["updated_at"] or ""),
            }
        )

    report: dict[str, Any] = {
        "databasePath": str(database),
        "date": target_date.isoformat(),
        "timezone": "Asia/Shanghai",
        "apply": bool(apply),
        "scanned": scanned,
        "candidates": len(items),
        "repaired": 0,
        "backupPath": "",
        "failures": [],
        "items": items,
    }
    if not apply or not items:
        return report

    destination = Path(backup_dir) if backup_dir else database.parent / "backups"
    report["backupPath"] = str(_backup_database(database, destination))
    try:
        with connect(database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for item in items:
                row = connection.execute(
                    "SELECT payload FROM resumes WHERE id = ?",
                    (item["resumeId"],),
                ).fetchone()
                if row is None:
                    raise RuntimeError(f"resume_missing:{item['resumeId']}")
                payload = _json_object(row["payload"])
                payload["name"] = item["newName"]
                payload["parsed_name"] = item["newName"]
                connection.execute(
                    "UPDATE resumes SET payload = ?, parsed_name = ? WHERE id = ?",
                    (
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        item["newName"],
                        item["resumeId"],
                    ),
                )
                if item["artifactId"]:
                    connection.execute(
                        "UPDATE resume_artifacts SET parsed_name = ? WHERE id = ?",
                        (item["newName"], item["artifactId"]),
                    )
            connection.commit()
        report["repaired"] = len(items)
    except Exception as error:
        report["failures"].append(f"{type(error).__name__}: {error}")
    return report


def _replacement_name(
    *,
    platform: str,
    current_name: str,
    platform_name: str,
    file_name: str,
) -> str:
    if platform in _ARTIFACT_PLATFORMS:
        if (
            is_trustworthy_resume_name(current_name)
            and not is_anonymous_resume_name(current_name)
            and is_anonymous_resume_name(platform_name)
        ):
            return current_name
        return choose_resume_name(
            platform_name=platform_name,
            document_name=current_name if is_trustworthy_resume_name(current_name) else "",
            file_name=file_name,
        )
    if platform == "boss":
        if current_name.strip():
            return current_name
        return choose_resume_name(
            platform_name=platform_name,
            file_name=file_name,
        )
    return current_name


def _load_rows(database: Path) -> list[sqlite3.Row]:
    with connect(database, read_only=True) as connection:
        return connection.execute(
            """
            SELECT id, payload, parsed_name, linked_platform, source_artifact_id, updated_at
            FROM resumes
            ORDER BY updated_at, id
            """
        ).fetchall()


def _load_artifacts(
    database: Path,
) -> tuple[dict[str, sqlite3.Row], dict[str, sqlite3.Row]]:
    with connect(database, read_only=True) as connection:
        rows = connection.execute(
            """
            SELECT id, resume_id, platform, candidate_name_from_platform, file_path
            FROM resume_artifacts
            WHERE parse_status = 'parsed'
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
    by_id = {str(row["id"]): row for row in rows}
    by_resume: dict[str, sqlite3.Row] = {}
    for row in rows:
        by_resume.setdefault(str(row["resume_id"]), row)
    return by_id, by_resume


def _beijing_date(value: str) -> date_type | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(BEIJING).date()


def _backup_database(database: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%SZ")
    destination = backup_dir / f"resumes-before-name-repair-{timestamp}.sqlite"
    with sqlite3.connect(database) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    return destination


def _json_object(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _first_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default=str(PROJECT_ROOT / "data" / "resumes.sqlite"),
    )
    parser.add_argument("--date", required=True, help="Beijing calendar date (YYYY-MM-DD)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir")
    args = parser.parse_args()
    report = repair_resume_names(
        args.database,
        date=args.date,
        apply=args.apply,
        backup_dir=args.backup_dir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
