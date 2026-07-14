from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from app.db.engine import run_migrations
from scripts.export_conversation_delta import export_conversation_delta
from scripts.import_conversation_delta import ConversationSyncConfig, run_sync


def test_import_script_can_run_directly_from_repository_root() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/import_conversation_delta.py", "--help"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--delta" in result.stdout


def test_export_creates_small_conversation_only_package(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    delta = tmp_path / "conversation_delta.sqlite"
    run_migrations(source)
    _insert_session(source, session_id="session-1")
    _insert_message(source, message_id="message-1", session_id="session-1")

    report = export_conversation_delta(source, delta)

    assert report["sessionCount"] == 1
    assert report["messageCount"] == 1
    assert report["quickCheck"] == "ok"
    assert report["orphanMessages"] == 0
    assert Path(report["manifestPath"]).is_file()
    assert Path(report["sha256Path"]).read_text(encoding="ascii").strip()
    manifest = json.loads(Path(report["manifestPath"]).read_text(encoding="utf-8"))
    assert manifest["sha256"] == report["sha256"]
    with sqlite3.connect(delta) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "conversation_sessions" in tables
        assert "conversation_messages" in tables
        assert "conversation_sync_metadata" in tables
        assert "resumes" not in tables


def test_dry_run_projects_changes_without_writing_target(tmp_path: Path) -> None:
    target = tmp_path / "target.sqlite"
    source = tmp_path / "source.sqlite"
    delta = tmp_path / "delta.sqlite"
    run_migrations(target)
    run_migrations(source)
    _insert_session(target, session_id="existing")
    _insert_message(target, message_id="existing-message", session_id="existing")
    _insert_session(source, session_id="existing")
    _insert_message(source, message_id="existing-message", session_id="existing")
    _insert_session(source, session_id="new-session", conversation_id="conversation-2")
    _insert_message(source, message_id="new-message", session_id="new-session")
    export_conversation_delta(source, delta)

    report = run_sync(ConversationSyncConfig(target_db=target, delta_db=delta))

    assert report["dryRun"] is True
    assert report["sourceSessions"] == 2
    assert report["sourceMessages"] == 2
    assert report["sessionsToInsert"] == 1
    assert report["messagesToInsert"] == 1
    assert report["projectedSessions"] == 2
    assert report["projectedMessages"] == 2
    assert _count(target, "conversation_sessions") == 1
    assert _count(target, "conversation_messages") == 1


def test_apply_maps_natural_identity_and_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "target.sqlite"
    source = tmp_path / "source.sqlite"
    delta = tmp_path / "delta.sqlite"
    backups = tmp_path / "backups"
    run_migrations(target)
    run_migrations(source)
    _insert_resume(target, resume_id="resume-1", linked_session_id="server-session")
    _insert_session(target, session_id="server-session", updated_at="2026-07-10T00:00:00+00:00")
    _insert_session(
        source,
        session_id="local-session",
        label="本地新标签",
        updated_at="2026-07-13T00:00:00+00:00",
    )
    _insert_message(source, message_id="local-message", session_id="local-session")
    export_conversation_delta(source, delta)
    config = ConversationSyncConfig(
        target_db=target,
        delta_db=delta,
        backup_dir=backups,
        apply=True,
        yes=True,
    )

    first = run_sync(config)
    second = run_sync(config)

    assert first["naturalIdentityMappings"] == 1
    assert first["sessionsToInsert"] == 0
    assert first["sessionsToUpdate"] == 1
    assert first["messagesToInsert"] == 1
    assert first["applied"] is True
    assert Path(first["backupPath"]).is_file()
    assert second["sessionsToInsert"] == 0
    assert second["messagesToInsert"] == 0
    assert _count(target, "conversation_sessions") == 1
    assert _count(target, "conversation_messages") == 1
    with sqlite3.connect(target) as connection:
        session_id, label = connection.execute(
            "SELECT session_id, text FROM conversation_messages WHERE id = 'local-message'"
        ).fetchone()
        assert session_id == "server-session"
        assert label == "你好"
        assert connection.execute(
            "SELECT label FROM conversation_sessions WHERE id = 'server-session'"
        ).fetchone()[0] == "本地新标签"
        assert connection.execute("SELECT COUNT(*) FROM resumes").fetchone()[0] == 1


def test_same_id_identity_conflict_blocks_apply(tmp_path: Path) -> None:
    target = tmp_path / "target.sqlite"
    source = tmp_path / "source.sqlite"
    delta = tmp_path / "delta.sqlite"
    run_migrations(target)
    run_migrations(source)
    _insert_session(target, session_id="session-1", owner="宋峰峰")
    _insert_session(source, session_id="session-1", owner="和新红")
    export_conversation_delta(source, delta)

    dry_run = run_sync(ConversationSyncConfig(target_db=target, delta_db=delta))

    assert dry_run["blockingConflictCount"] == 1
    assert dry_run["blockingConflicts"][0]["type"] == "session_identity_conflict"
    with pytest.raises(RuntimeError, match="conversation_sync_blocking_conflicts"):
        run_sync(
            ConversationSyncConfig(
                target_db=target,
                delta_db=delta,
                backup_dir=tmp_path / "backups",
                apply=True,
                yes=True,
            )
        )


def test_same_message_id_with_different_content_blocks_apply(tmp_path: Path) -> None:
    target = tmp_path / "target.sqlite"
    source = tmp_path / "source.sqlite"
    delta = tmp_path / "delta.sqlite"
    run_migrations(target)
    run_migrations(source)
    _insert_session(target, session_id="session-1")
    _insert_session(source, session_id="session-1")
    _insert_message(target, message_id="message-1", session_id="session-1", text="服务器")
    _insert_message(source, message_id="message-1", session_id="session-1", text="本地")
    export_conversation_delta(source, delta)

    report = run_sync(ConversationSyncConfig(target_db=target, delta_db=delta))

    assert report["blockingConflictCount"] == 1
    assert report["blockingConflicts"][0]["type"] == "message_content_conflict"


def _insert_resume(database: Path, *, resume_id: str, linked_session_id: str) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO resumes (
              id, payload, linked_session_id, linked_platform, linked_owner, updated_at
            ) VALUES (?, '{}', ?, 'job51', '宋峰峰', '2026-07-13T00:00:00+00:00')
            """,
            (resume_id, linked_session_id),
        )
        connection.commit()


def _insert_session(
    database: Path,
    *,
    session_id: str,
    owner: str = "宋峰峰",
    conversation_id: str = "conversation-1",
    label: str = "",
    updated_at: str = "2026-07-13T00:00:00+00:00",
) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO conversation_sessions (
              id, platform, owner, candidate_name, position, applied_position,
              platform_conversation_id, label, current_stage, next_action,
              recent_messages_fingerprint, identity_confidence, identity_warnings,
              last_seen_at, created_at, updated_at
            ) VALUES (?, 'job51', ?, '候选人', 'AI产品经理', 'AI产品经理', ?, ?, '', '',
                      '', 'high', '[]', ?, '2026-07-01T00:00:00+00:00', ?)
            """,
            (session_id, owner, conversation_id, label, updated_at, updated_at),
        )
        connection.commit()


def _insert_message(
    database: Path,
    *,
    message_id: str,
    session_id: str,
    text: str = "你好",
) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO conversation_messages (
              id, session_id, sender, text, raw_text, sent_at,
              platform_message_id, message_hash, created_at
            ) VALUES (?, ?, 'other', ?, ?, '10:00', '', ?, '2026-07-13T00:00:00+00:00')
            """,
            (message_id, session_id, text, text, f"hash-{message_id}-{text}"),
        )
        connection.commit()


def _count(database: Path, table: str) -> int:
    with sqlite3.connect(database) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
