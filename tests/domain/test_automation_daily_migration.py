from __future__ import annotations

import hashlib
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from app.db.engine import run_migrations
from app.domain.automation_monitoring.daily_projection import DailyProjectionExport
from app.domain.automation_monitoring.models import AutomationContactEvent
from scripts.migrate_automation_daily_events import (
    build_export_package,
    export_resume_artifacts,
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
    assert first["version"] == 2
    assert first["timezone"] == "Asia/Shanghai"
    assert first["startDate"] == "2026-07-14"
    assert first["endDate"] == "2026-07-20"
    assert first["coverage"] == {"events": 1, "unresolvedRecords": 0}
    assert first["summary"] == {"totalEvents": 1}
    assert first["artifacts"] == []
    assert first["events"][0]["candidateName"] == "张三"
    assert package_sha256(first) == package_sha256(second)


def test_import_dry_run_does_not_write_events(tmp_path: Path) -> None:
    database = tmp_path / "server.sqlite"
    run_migrations(database)
    package = _package()

    result = import_package(
        database_path=database,
        package=package,
        expected_sha256=package_sha256(package),
        apply=False,
    )

    assert result == {
        "validated": 1,
        "validatedArtifacts": 0,
        "applied": 0,
        "appliedArtifacts": 0,
        "dryRun": True,
    }
    assert _event_count(database) == 0


def test_import_apply_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "server.sqlite"
    run_migrations(database)
    package = _package()

    expected_sha256 = package_sha256(package)
    first = import_package(
        database_path=database,
        package=package,
        expected_sha256=expected_sha256,
        apply=True,
    )
    second = import_package(
        database_path=database,
        package=package,
        expected_sha256=expected_sha256,
        apply=True,
    )

    assert first == {
        "validated": 1,
        "validatedArtifacts": 0,
        "applied": 1,
        "appliedArtifacts": 0,
        "dryRun": False,
    }
    assert second == first
    assert _event_count(database) == 1


def test_import_rejects_sha_mismatch_before_opening_database(tmp_path: Path) -> None:
    database = tmp_path / "server.sqlite"
    package = _package()

    with pytest.raises(ValueError, match="package sha256 mismatch"):
        import_package(
            database_path=database,
            package=package,
            expected_sha256="0" * 64,
            apply=True,
        )

    assert not database.exists()


def test_export_and_import_pending_resume_artifact_bundle(tmp_path: Path) -> None:
    source_database = tmp_path / "source.sqlite"
    run_migrations(source_database)
    source_file = tmp_path / "source" / "candidate.pdf"
    source_file.parent.mkdir()
    source_file.write_bytes(b"%PDF-1.4\nresume bundle\n%%EOF")
    file_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()
    with sqlite3.connect(source_database) as connection:
        connection.execute(
            """
            INSERT INTO resume_artifacts (
              id, session_id, platform, owner, platform_conversation_id,
              candidate_name_from_platform, position, file_path, file_hash,
              source_kind, parse_status, parsed_name, resume_id, error,
              created_at, updated_at
            ) VALUES (?, ?, 'job51', 'owner', '', 'candidate', 'job', ?, ?,
                      'attachment', 'pending', '', '', '', ?, ?)
            """,
            (
                "artifact-bundle",
                "session-1",
                str(source_file),
                file_hash,
                "2026-07-20T01:00:00+00:00",
                "2026-07-20T01:00:00+00:00",
            ),
        )
        connection.commit()
    event = _event().model_copy(
        update={
            "resume_acquired": True,
            "resume_handling": "local_resume_downloaded",
            "resume_file_hash": file_hash,
        }
    )
    files_dir = tmp_path / "bundle-files"

    artifacts = export_resume_artifacts(
        database_path=source_database,
        events=[event],
        files_dir=files_dir,
    )
    package = build_export_package(
        DailyProjectionExport(
            events=[event],
            coverage={"events": 1},
            summary={"totalEvents": 1},
        ),
        start_date=date(2026, 7, 14),
        end_date=date(2026, 7, 20),
        generated_at="2026-07-20T08:00:00+00:00",
        artifacts=artifacts,
    )
    target_database = tmp_path / "target" / "resumes.sqlite"

    first = import_package(
        database_path=target_database,
        package=package,
        expected_sha256=package_sha256(package),
        files_dir=files_dir,
        apply=True,
    )
    second = import_package(
        database_path=target_database,
        package=package,
        expected_sha256=package_sha256(package),
        files_dir=files_dir,
        apply=True,
    )

    assert first["validatedArtifacts"] == 1
    assert first["appliedArtifacts"] == 1
    assert second == first
    with sqlite3.connect(target_database) as connection:
        row = connection.execute(
            "SELECT file_path, file_hash, parse_status FROM resume_artifacts"
        ).fetchone()
    assert row is not None
    imported_file = Path(row[0])
    assert imported_file.is_file()
    assert imported_file.read_bytes() == source_file.read_bytes()
    assert row[1:] == (file_hash, "pending")
    assert _event_count(target_database) == 1


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
