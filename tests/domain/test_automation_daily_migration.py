from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from app.db.engine import run_migrations
from app.domain.automation_monitoring.daily_projection import DailyProjectionExport
from app.domain.automation_monitoring.models import AutomationContactEvent
from scripts.migrate_automation_daily_events import (
    build_export_package,
    import_package,
    package_sha256,
    validate_package,
)


def test_export_package_is_stable() -> None:
    exported = DailyProjectionExport(
        events=[_event()],
        coverage={"events": 1, "unresolvedRecords": 0},
        summary={"totalEvents": 1},
    )

    first = build_export_package(
        exported,
        start_date=date(2026, 7, 14),
        end_date=date(2026, 7, 20),
        generated_at="2026-07-20T08:00:00+00:00",
    )
    second = build_export_package(
        exported,
        start_date=date(2026, 7, 14),
        end_date=date(2026, 7, 20),
        generated_at="2026-07-20T08:00:00+00:00",
    )

    assert first == second
    assert first["version"] == 1
    assert first["timezone"] == "Asia/Shanghai"
    assert first["startDate"] == "2026-07-14"
    assert first["endDate"] == "2026-07-20"
    assert first["coverage"] == {"events": 1, "unresolvedRecords": 0}
    assert first["summary"] == {"totalEvents": 1}
    assert first["events"][0]["candidateName"] == "张三"
    assert package_sha256(first) == package_sha256(second)


def test_import_dry_run_does_not_write_events(tmp_path: Path) -> None:
    database = tmp_path / "server.sqlite"
    run_migrations(database)
    package = _package()

    result = import_package(database_path=database, package=package, apply=False)

    assert result == {"validated": 1, "applied": 0, "dryRun": True}
    assert _event_count(database) == 0


def test_import_apply_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "server.sqlite"
    run_migrations(database)
    package = _package()

    first = import_package(database_path=database, package=package, apply=True)
    second = import_package(database_path=database, package=package, apply=True)

    assert first == {"validated": 1, "applied": 1, "dryRun": False}
    assert second == {"validated": 1, "applied": 1, "dryRun": False}
    assert _event_count(database) == 1


def test_validate_package_rejects_conflicting_duplicate_ids() -> None:
    package = _package()
    duplicate = dict(package["events"][0])
    duplicate["action"] = "answer_question"
    package["events"].append(duplicate)

    with pytest.raises(ValueError, match="conflicting duplicate event id"):
        validate_package(package)


def test_validate_package_rejects_event_outside_range() -> None:
    package = _package()
    package["events"][0]["occurredAt"] = "2026-07-21T01:00:00+00:00"

    with pytest.raises(ValueError, match="outside package date range"):
        validate_package(package)


def _package() -> dict[str, object]:
    return build_export_package(
        DailyProjectionExport(
            events=[_event()],
            coverage={"events": 1},
            summary={"totalEvents": 1},
        ),
        start_date=date(2026, 7, 14),
        end_date=date(2026, 7, 20),
        generated_at="2026-07-20T08:00:00+00:00",
    )


def _event() -> AutomationContactEvent:
    return AutomationContactEvent(
        id="automation-daily-2026-07-20-test",
        contactKey="session|session-1",
        owner="和新红",
        platform="job51",
        candidateName="张三",
        jobType="AI产品经理",
        occurredAt="2026-07-20T01:00:00+00:00",
        action="request_resume",
        stage="resume_requested",
        processed=True,
        requestedResume=True,
        payload={"date": "2026-07-20", "sessionId": "session-1"},
        updatedAt="2026-07-20T01:00:00+00:00",
    )


def _event_count(database: Path) -> int:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM automation_contact_events"
        ).fetchone()
    return int(row[0])
