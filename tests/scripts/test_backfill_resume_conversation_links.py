from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from app.db.engine import run_migrations
from app.domain.conversation.models import ConversationSession
from app.domain.conversation.repository import ConversationRepository
from app.platforms.types import ChatMessage, MessageSender
from scripts.backfill_resume_conversation_links import BackfillConfig, run_backfill


def test_backfill_dry_run_reports_unique_link_without_writing(tmp_path: Path) -> None:
    database = tmp_path / "resumes.sqlite"
    _seed_database(database)

    report = run_backfill(BackfillConfig(database=database))

    assert report["dryRun"] is True
    assert report["scanned"] == 3
    assert report["wouldLink"] == 1
    assert report["ambiguous"] == 1
    assert report["withoutMessages"] == 1
    assert _resume_link(database, "resume-unique") == ""


def test_backfill_apply_updates_only_unique_message_bearing_session(tmp_path: Path) -> None:
    database = tmp_path / "resumes.sqlite"
    _seed_database(database)

    report = run_backfill(
        BackfillConfig(database=database, apply=True, yes=True, backup=True)
    )

    assert report["linked"] == 1
    assert Path(report["backupPath"]).is_file()
    assert _resume_link(database, "resume-unique") == "session-unique"
    assert _resume_link(database, "resume-ambiguous") == ""
    assert _resume_link(database, "resume-no-messages") == ""
    payload = _resume_payload(database, "resume-unique")
    assert payload["linked_session_id"] == "session-unique"
    assert payload["linked_platform_conversation_id"] == "conversation-unique"


def test_backfill_apply_requires_explicit_confirmation(tmp_path: Path) -> None:
    database = tmp_path / "resumes.sqlite"
    _seed_database(database)

    with pytest.raises(RuntimeError, match="apply_requires_yes"):
        run_backfill(BackfillConfig(database=database, apply=True))


def test_backfill_script_runs_directly_from_project_root(tmp_path: Path) -> None:
    database = tmp_path / "resumes.sqlite"
    _seed_database(database)
    project_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [
            sys.executable,
            "scripts/backfill_resume_conversation_links.py",
            "--database",
            str(database),
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["wouldLink"] == 1


def _seed_database(database: Path) -> None:
    run_migrations(database)
    repository = ConversationRepository(database)
    sessions = [
        ConversationSession(
            id="session-unique",
            platform="boss",
            owner="owner",
            candidate_name="Unique Candidate",
            position="AI产品经理",
            platform_conversation_id="conversation-unique",
        ),
        ConversationSession(
            id="session-ambiguous-a",
            platform="boss",
            owner="owner",
            candidate_name="Ambiguous Candidate",
            position="AI产品经理",
        ),
        ConversationSession(
            id="session-ambiguous-b",
            platform="boss",
            owner="owner",
            candidate_name="Ambiguous Candidate",
            position="AI产品经理",
        ),
        ConversationSession(
            id="session-no-messages",
            platform="boss",
            owner="owner",
            candidate_name="Silent Candidate",
            position="AI产品经理",
        ),
    ]
    for session in sessions:
        repository.save_session(session)
    for session_id in ("session-unique", "session-ambiguous-a", "session-ambiguous-b"):
        repository.upsert_messages(
            session_id,
            [ChatMessage(sender=MessageSender.CANDIDATE, text="hello")],
        )
    with sqlite3.connect(database) as connection:
        for resume_id, name in (
            ("resume-unique", "Unique Candidate"),
            ("resume-ambiguous", "Ambiguous Candidate"),
            ("resume-no-messages", "Silent Candidate"),
        ):
            payload = {
                "name": name,
                "platform": "boss",
                "accountName": "owner",
                "jobType": "AI PM",
            }
            connection.execute(
                """
                INSERT INTO resumes (
                  id, payload, phone_key, job_type, match_score, updated_at,
                  parsed_name, linked_platform, linked_owner
                ) VALUES (?, ?, '', ?, 0, ?, ?, 'boss', 'owner')
                """,
                (
                    resume_id,
                    json.dumps(payload, ensure_ascii=False),
                    "AI PM",
                    "2026-07-18T00:00:00+00:00",
                    name,
                ),
            )
        connection.commit()


def _resume_link(database: Path, resume_id: str) -> str:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT linked_session_id FROM resumes WHERE id = ?", (resume_id,)
        ).fetchone()
    return str(row[0] or "")


def _resume_payload(database: Path, resume_id: str) -> dict[str, object]:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT payload FROM resumes WHERE id = ?", (resume_id,)
        ).fetchone()
    return json.loads(str(row[0]))
