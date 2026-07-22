"""Historical resume-name repair regression tests."""

from __future__ import annotations

import json
from pathlib import Path

from app.db.engine import connect, run_migrations
from scripts.repair_resume_names import repair_resume_names


def test_repair_resume_names_is_dry_run_by_default_and_preserves_timestamps(
    tmp_path: Path,
) -> None:
    database = tmp_path / "resumes.sqlite"
    run_migrations(database)
    _insert_resume(
        database,
        resume_id="resume-job51",
        parsed_name="应聘职位",
        payload={"name": "应聘职位", "parsed_name": "应聘职位"},
        platform="job51",
        updated_at="2026-07-21T13:56:46.264126+08:00",
        source_artifact_id="artifact-job51",
    )
    _insert_artifact(
        database,
        artifact_id="artifact-job51",
        resume_id="resume-job51",
        platform="job51",
        platform_name="蔡希玮",
        file_path="51job_蔡希玮_AI 产品经理_c36b898f.pdf",
        parsed_name="应聘职位",
    )
    _insert_resume(
        database,
        resume_id="resume-anonymous",
        parsed_name="周浩然",
        payload={"name": "周浩然", "parsed_name": "周浩然"},
        platform="job51",
        updated_at="2026-07-21T18:23:36.331340+08:00",
        source_artifact_id="artifact-anonymous",
    )
    _insert_artifact(
        database,
        artifact_id="artifact-anonymous",
        resume_id="resume-anonymous",
        platform="job51",
        platform_name="周先生",
        file_path="51job_周先生_AI 产品经理_0ff83d5d.pdf",
        parsed_name="周浩然",
    )
    _insert_resume(
        database,
        resume_id="resume-boss-full",
        parsed_name="李尧川",
        payload={"name": "李尧川", "filePath": "【AI产品经理】李生_10年.pdf"},
        platform="boss",
        updated_at="2026-07-21T20:00:00+08:00",
    )
    _insert_resume(
        database,
        resume_id="resume-boss-empty",
        parsed_name="",
        payload={"name": "", "filePath": "邮箱_8205_【AI产品经理】刘帅_10年.pdf"},
        platform="boss",
        updated_at="2026-07-21T21:05:49.391000+08:00",
    )

    dry_run = repair_resume_names(database, date="2026-07-21")

    assert dry_run["apply"] is False
    assert dry_run["candidates"] == 2
    assert _resume_row(database, "resume-job51")["parsed_name"] == "应聘职位"

    applied = repair_resume_names(
        database,
        date="2026-07-21",
        apply=True,
        backup_dir=tmp_path / "backups",
    )

    assert applied["repaired"] == 2
    assert Path(applied["backupPath"]).exists()
    job51 = _resume_row(database, "resume-job51")
    job51_payload = json.loads(job51["payload"])
    assert job51["parsed_name"] == "蔡希玮"
    assert job51_payload["name"] == "蔡希玮"
    assert job51_payload["parsed_name"] == "蔡希玮"
    assert job51["updated_at"] == "2026-07-21T13:56:46.264126+08:00"
    assert _artifact_name(database, "artifact-job51") == "蔡希玮"
    assert _resume_row(database, "resume-anonymous")["parsed_name"] == "周浩然"
    assert _resume_row(database, "resume-boss-full")["parsed_name"] == "李尧川"
    assert _resume_row(database, "resume-boss-empty")["parsed_name"] == "刘帅"


def test_repair_resume_names_filters_by_beijing_calendar_date(tmp_path: Path) -> None:
    database = tmp_path / "resumes.sqlite"
    run_migrations(database)
    _insert_resume(
        database,
        resume_id="previous-local-day",
        parsed_name="",
        payload={"name": "", "filePath": "【AI产品经理】张三_5年.pdf"},
        platform="boss",
        updated_at="2026-07-20T15:59:59+00:00",
    )
    _insert_resume(
        database,
        resume_id="target-local-day",
        parsed_name="",
        payload={"name": "", "filePath": "【AI产品经理】李四_5年.pdf"},
        platform="boss",
        updated_at="2026-07-20T16:00:00+00:00",
    )

    report = repair_resume_names(database, date="2026-07-21")

    assert report["candidates"] == 1
    assert report["items"][0]["resumeId"] == "target-local-day"


def _insert_resume(
    database: Path,
    *,
    resume_id: str,
    parsed_name: str,
    payload: dict[str, object],
    platform: str,
    updated_at: str,
    source_artifact_id: str = "",
) -> None:
    with connect(database) as connection:
        connection.execute(
            """
            INSERT INTO resumes (
              id, payload, phone_key, job_type, match_score, updated_at,
              parsed_name, linked_session_id, linked_platform, linked_owner,
              linked_platform_conversation_id, source_artifact_id
            ) VALUES (?, ?, '', 'AI产品经理', NULL, ?, ?, '', ?, '', '', ?)
            """,
            (
                resume_id,
                json.dumps(payload, ensure_ascii=False),
                updated_at,
                parsed_name,
                platform,
                source_artifact_id,
            ),
        )
        connection.commit()


def _insert_artifact(
    database: Path,
    *,
    artifact_id: str,
    resume_id: str,
    platform: str,
    platform_name: str,
    file_path: str,
    parsed_name: str,
) -> None:
    with connect(database) as connection:
        session_id = f"session-{artifact_id}"
        connection.execute(
            """
            INSERT INTO conversation_sessions (
              id, platform, owner, candidate_name, position, applied_position,
              platform_conversation_id, label, current_stage, next_action,
              recent_messages_fingerprint, identity_confidence, identity_warnings,
              last_seen_at, created_at, updated_at
            ) VALUES (?, ?, 'owner', ?, 'AI产品经理', 'AI产品经理', ?, '', '', '', '', '',
                      '[]', ?, ?, ?)
            """,
            (
                session_id,
                platform,
                platform_name,
                f"conversation-{artifact_id}",
                "2026-07-21T12:00:00+08:00",
                "2026-07-21T12:00:00+08:00",
                "2026-07-21T12:00:00+08:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO resume_artifacts (
              id, session_id, platform, owner, platform_conversation_id,
              candidate_name_from_platform, position, file_path, file_hash,
              source_kind, parse_status, parsed_name, resume_id, error,
              created_at, updated_at
            ) VALUES (?, ?, ?, 'owner', 'conversation', ?, 'AI产品经理', ?, ?,
                      'attachment', 'parsed', ?, ?, '', ?, ?)
            """,
            (
                artifact_id,
                session_id,
                platform,
                platform_name,
                file_path,
                f"hash-{artifact_id}",
                parsed_name,
                resume_id,
                "2026-07-21T12:00:00+08:00",
                "2026-07-21T12:00:00+08:00",
            ),
        )
        connection.commit()


def _resume_row(database: Path, resume_id: str):
    with connect(database, read_only=True) as connection:
        return connection.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()


def _artifact_name(database: Path, artifact_id: str) -> str:
    with connect(database, read_only=True) as connection:
        row = connection.execute(
            "SELECT parsed_name FROM resume_artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
    return str(row["parsed_name"])
