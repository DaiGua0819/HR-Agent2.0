"""Move legacy local-admin resume tasks into the shared administrator inbox.

The command is read-only by default.  Use ``--apply`` only after reviewing the
reported task count against the intended production migration.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.engine import connect, run_migrations  # noqa: E402
from app.domain.resume_review.models import SHARED_ADMIN_INBOX  # noqa: E402
from app.settings import load_settings  # noqa: E402

LEGACY_LOCAL_ADMIN = "local-admin"
MIGRATION_ACTOR = "shared-admin-inbox-migration"


def migrate_assignments(database_path: str | Path, *, apply: bool = False) -> dict[str, object]:
    """Report or apply the idempotent local-admin to shared-inbox migration."""

    database = Path(database_path)
    if apply:
        run_migrations(database)

    with connect(database, read_only=not apply) as connection:
        legacy_rows = connection.execute(
            """
            SELECT * FROM resume_assignments
            WHERE assigned_to_user_id = ? AND status = 'pending'
            ORDER BY resume_id, updated_at DESC, id DESC
            """,
            (LEGACY_LOCAL_ADMIN,),
        ).fetchall()
        report = _report(legacy_rows, database=database, apply=apply)
        if not apply:
            return report

        grouped_legacy = _group_by_resume(legacy_rows)
        migrated = 0
        superseded = 0
        state_updates = 0
        connection.execute("BEGIN IMMEDIATE")
        for resume_id, _rows in grouped_legacy.items():
            pending_rows = connection.execute(
                """
                SELECT * FROM resume_assignments
                WHERE resume_id = ?
                  AND status = 'pending'
                  AND assigned_to_user_id IN (?, ?)
                ORDER BY updated_at DESC, id DESC
                """,
                (resume_id, LEGACY_LOCAL_ADMIN, SHARED_ADMIN_INBOX),
            ).fetchall()
            if not pending_rows:
                continue
            winner = pending_rows[0]
            if winner["assigned_to_user_id"] == LEGACY_LOCAL_ADMIN:
                _update_assignment_target(connection, winner["id"])
                migrated += 1
                _append_event(
                    connection,
                    resume_id=resume_id,
                    event_type="assignment_migrated_to_shared_inbox",
                    before=_assignment_payload(winner),
                    after=_assignment_payload_by_id(connection, winner["id"]),
                )

            for duplicate in pending_rows[1:]:
                _supersede_assignment(connection, duplicate["id"])
                superseded += 1
                _append_event(
                    connection,
                    resume_id=resume_id,
                    event_type="assignment_migration_superseded",
                    before=_assignment_payload(duplicate),
                    after=_assignment_payload_by_id(connection, duplicate["id"]),
                )

            cursor = connection.execute(
                """
                UPDATE resume_review_states
                SET assigned_to = ?, updated_at = ?
                WHERE resume_id = ? AND assigned_to = ?
                """,
                (SHARED_ADMIN_INBOX, _now(), resume_id, LEGACY_LOCAL_ADMIN),
            )
            state_updates += cursor.rowcount
        connection.commit()

    report["migratedAssignments"] = migrated
    report["supersededAssignments"] = superseded
    report["updatedReviewStates"] = state_updates
    return report


def parse_args() -> argparse.Namespace:
    """Parse the explicit migration command-line contract."""

    parser = argparse.ArgumentParser(
        description="Migrate pending local-admin resume review tasks to shared-admin-inbox."
    )
    parser.add_argument("--database", default="", help="SQLite database path; defaults to settings")
    parser.add_argument("--apply", action="store_true", help="Write the migration after reporting")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database = Path(args.database) if args.database else load_settings().resolved_database_path
    report = migrate_assignments(database, apply=bool(args.apply))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


def _report(rows: list[Any], *, database: Path, apply: bool) -> dict[str, object]:
    grouped = _group_by_resume(rows)
    return {
        "database": str(database),
        "apply": apply,
        "pendingLegacyAssignments": len(rows),
        "affectedResumes": len(grouped),
        "duplicatePendingAssignments": sum(max(0, len(items) - 1) for items in grouped.values()),
        "migratedAssignments": 0,
        "supersededAssignments": 0,
        "updatedReviewStates": 0,
    }


def _group_by_resume(rows: list[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[str(row["resume_id"])].append(row)
    return grouped


def _update_assignment_target(connection: Any, assignment_id: str) -> None:
    connection.execute(
        """
        UPDATE resume_assignments
        SET assigned_to_user_id = ?, updated_at = ?
        WHERE id = ? AND assigned_to_user_id = ? AND status = 'pending'
        """,
        (SHARED_ADMIN_INBOX, _now(), assignment_id, LEGACY_LOCAL_ADMIN),
    )


def _supersede_assignment(connection: Any, assignment_id: str) -> None:
    connection.execute(
        """
        UPDATE resume_assignments
        SET status = 'superseded', updated_at = ?
        WHERE id = ? AND status = 'pending'
        """,
        (_now(), assignment_id),
    )


def _assignment_payload_by_id(connection: Any, assignment_id: str) -> dict[str, object]:
    row = connection.execute(
        "SELECT * FROM resume_assignments WHERE id = ?",
        (assignment_id,),
    ).fetchone()
    assert row is not None
    return _assignment_payload(row)


def _assignment_payload(row: Any) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "resumeId": str(row["resume_id"]),
        "fromUserId": str(row["from_user_id"]),
        "assignedToUserId": str(row["assigned_to_user_id"]),
        "status": str(row["status"]),
    }


def _append_event(
    connection: Any,
    *,
    resume_id: str,
    event_type: str,
    before: dict[str, object],
    after: dict[str, object],
) -> None:
    connection.execute(
        """
        INSERT INTO resume_review_events (
          id, resume_id, user_id, event_type, before_json, after_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid4().hex,
            resume_id,
            MIGRATION_ACTOR,
            event_type,
            json.dumps(before, ensure_ascii=False, sort_keys=True),
            json.dumps(after, ensure_ascii=False, sort_keys=True),
            _now(),
        ),
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":  # pragma: no cover - command-line wrapper
    raise SystemExit(main())
