"""Safely backfill missing resume-to-conversation links."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.domain.conversation.matching import resolve_unique_conversation  # noqa: E402
from app.domain.conversation.repository import ConversationRepository  # noqa: E402
from app.domain.resume.source import normalize_source_platform  # noqa: E402


@dataclass(frozen=True)
class BackfillConfig:
    database: Path
    apply: bool = False
    yes: bool = False
    backup: bool = False


def run_backfill(config: BackfillConfig) -> dict[str, Any]:
    if not config.database.is_file():
        raise FileNotFoundError(f"database_not_found: {config.database}")
    if config.apply and not config.yes:
        raise RuntimeError("apply_requires_yes")

    repository = ConversationRepository(config.database, migrate=False)
    report: dict[str, Any] = {
        "dryRun": not config.apply,
        "database": str(config.database),
        "scanned": 0,
        "wouldLink": 0,
        "linked": 0,
        "ambiguous": 0,
        "withoutMessages": 0,
        "missing": 0,
        "backupPath": "",
        "samples": [],
    }
    updates: list[dict[str, Any]] = []
    for row in _load_unlinked_rows(config.database):
        report["scanned"] += 1
        payload = _decode_payload(row["payload"])
        name = _first_text(row["parsed_name"], payload.get("name"), payload.get("candidateName"))
        position = _first_text(row["job_type"], payload.get("jobType"), payload.get("position"))
        platform = _platform_for_row(row, payload)
        owner = _first_text(
            row["linked_owner"],
            payload.get("accountName"),
            payload.get("sourceName"),
            payload.get("owner"),
            payload.get("account"),
            payload.get("operator"),
        )
        match = resolve_unique_conversation(
            repository,
            candidate_name=name,
            position=position,
            platform=platform,
            owner=owner,
        )
        if match.session is not None:
            report["wouldLink"] += 1
            updates.append({"row": row, "payload": payload, "session": match.session})
            continue
        if match.reason == "conversation_ambiguous":
            report["ambiguous"] += 1
            category = "ambiguous"
        elif match.candidate_count == 1:
            report["withoutMessages"] += 1
            category = "withoutMessages"
        else:
            report["missing"] += 1
            category = "missing"
        if len(report["samples"]) < 20:
            report["samples"].append(
                {
                    "resumeId": str(row["id"]),
                    "name": name,
                    "jobType": position,
                    "platform": platform,
                    "owner": owner,
                    "category": category,
                }
            )

    if not config.apply or not updates:
        return report
    if config.backup:
        report["backupPath"] = str(_backup_database(config.database))

    with closing(sqlite3.connect(config.database, timeout=30)) as connection:
        connection.execute("PRAGMA busy_timeout = 30000")
        for item in updates:
            row = item["row"]
            payload = dict(item["payload"])
            session = item["session"]
            payload["linked_session_id"] = session.id
            payload["linked_platform"] = session.platform
            payload["linked_owner"] = session.owner
            if session.platform_conversation_id:
                payload["linked_platform_conversation_id"] = session.platform_conversation_id
            cursor = connection.execute(
                """
                UPDATE resumes SET
                  payload = ?, linked_session_id = ?, linked_platform = ?, linked_owner = ?,
                  linked_platform_conversation_id = ?
                WHERE id = ? AND COALESCE(linked_session_id, '') = ''
                """,
                (
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    session.id,
                    session.platform,
                    session.owner,
                    session.platform_conversation_id,
                    row["id"],
                ),
            )
            report["linked"] += cursor.rowcount
        connection.commit()
    return report


def _load_unlinked_rows(database: Path) -> list[sqlite3.Row]:
    uri = database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as connection:
        connection.row_factory = sqlite3.Row
        return list(
            connection.execute(
                """
                SELECT id, payload, parsed_name, job_type, linked_platform, linked_owner
                FROM resumes
                WHERE COALESCE(linked_session_id, '') = ''
                ORDER BY updated_at DESC
                """
            )
        )


def _platform_for_row(row: sqlite3.Row, payload: dict[str, Any]) -> str:
    raw = _first_text(
        row["linked_platform"],
        payload.get("sourcePlatform"),
        payload.get("platform"),
        payload.get("source"),
    )
    return normalize_source_platform(raw) or raw.lower()


def _decode_payload(value: object) -> dict[str, Any]:
    try:
        payload = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _backup_database(database: Path) -> Path:
    backup_dir = database.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"resumes_before_conversation_link_backfill_{timestamp}.sqlite"
    source_uri = database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True, timeout=30)) as source:
        with closing(sqlite3.connect(backup_path)) as destination:
            source.backup(destination)
    return backup_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default=str(PROJECT_ROOT / "data" / "resumes.sqlite"),
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--backup", action="store_true")
    args = parser.parse_args()
    report = run_backfill(
        BackfillConfig(
            database=Path(args.database),
            apply=args.apply,
            yes=args.yes,
            backup=args.backup,
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
