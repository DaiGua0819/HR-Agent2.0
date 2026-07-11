"""Tests for migrating legacy local-admin review tasks into the shared inbox."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.db.engine import connect
from app.domain.resume_review.models import SHARED_ADMIN_INBOX
from app.domain.resume_review.repository import ResumeReviewRepository
from scripts.migrate_local_admin_assignments_to_shared_inbox import migrate_assignments

ROOT = Path(__file__).resolve().parents[2]


def test_migration_is_dry_run_by_default_and_apply_moves_legacy_pending_task(
    tmp_path: Path,
) -> None:
    """The migration reports first, then moves both assignment and reviewer push state on apply."""

    database = tmp_path / "review.sqlite"
    repository = ResumeReviewRepository(database)
    repository.upsert_state(
        resume_id="resume-1",
        user_id="local-member",
        user_name="普通成员",
        decision="suitable",
        assigned_to="local-admin",
    )
    repository.create_assignment(
        resume_id="resume-1",
        from_user_id="local-member",
        assigned_to_user_id="local-admin",
        source_decision_id="decision-1",
        note="历史推送",
    )

    dry_run = migrate_assignments(database, apply=False)

    assert dry_run["pendingLegacyAssignments"] == 1
    assert dry_run["migratedAssignments"] == 0
    assert repository.list_assignments("local-admin")[0].assigned_to_user_id == "local-admin"

    applied = migrate_assignments(database, apply=True)

    assert applied["migratedAssignments"] == 1
    assert repository.list_assignments("local-admin") == []
    assert repository.list_assignments(SHARED_ADMIN_INBOX)[0].resume_id == "resume-1"
    assert repository.get_state("resume-1", "local-member").assigned_to == SHARED_ADMIN_INBOX
    with connect(database) as connection:
        events = connection.execute(
            "SELECT event_type FROM resume_review_events WHERE resume_id = ?",
            ("resume-1",),
        ).fetchall()
    assert "assignment_migrated_to_shared_inbox" in {event["event_type"] for event in events}


def test_apply_keeps_only_the_latest_pending_assignment_per_resume(tmp_path: Path) -> None:
    """A legacy/shared duplicate pair becomes one pending shared-inbox task."""

    database = tmp_path / "review.sqlite"
    repository = ResumeReviewRepository(database)
    legacy = repository.create_assignment(
        resume_id="resume-1",
        from_user_id="local-member",
        assigned_to_user_id="local-admin",
        source_decision_id="legacy",
        note="历史任务",
    )
    repository.create_assignment(
        resume_id="resume-1",
        from_user_id="new-member",
        assigned_to_user_id=SHARED_ADMIN_INBOX,
        source_decision_id="shared",
        note="新任务",
    )
    with connect(database) as connection:
        connection.execute(
            "UPDATE resume_assignments SET updated_at = ? WHERE id = ?",
            ("9999-01-01T00:00:00+00:00", legacy.id),
        )

    report = migrate_assignments(database, apply=True)

    with connect(database) as connection:
        rows = connection.execute(
            "SELECT assigned_to_user_id, status FROM resume_assignments WHERE resume_id = ?",
            ("resume-1",),
        ).fetchall()
    assert report["migratedAssignments"] == 1
    assert report["supersededAssignments"] == 1
    assert [(row["assigned_to_user_id"], row["status"]) for row in rows].count(
        (SHARED_ADMIN_INBOX, "pending")
    ) == 1
    assert [row["status"] for row in rows].count("superseded") == 1


def test_migration_script_runs_against_its_own_worktree_package(tmp_path: Path) -> None:
    """Direct script execution must not import a sibling worktree's old app package."""

    database = tmp_path / "review.sqlite"
    ResumeReviewRepository(database)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "migrate_local_admin_assignments_to_shared_inbox.py"),
            "--database",
            str(database),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["apply"] is False
