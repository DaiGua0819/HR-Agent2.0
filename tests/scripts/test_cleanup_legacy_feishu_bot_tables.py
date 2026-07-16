from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import scripts.cleanup_legacy_feishu_bot_tables as cleanup_module
from scripts.cleanup_legacy_feishu_bot_tables import cleanup_legacy_tables

LEGACY_SCHEMA = """
CREATE TABLE feishu_bot_events (
  event_id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL UNIQUE,
  sender_open_id TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  chat_type TEXT NOT NULL DEFAULT '',
  message_type TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'received',
  response_message_id TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
  received_at TEXT NOT NULL,
  started_at TEXT NOT NULL DEFAULT '',
  completed_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_feishu_bot_events_sender
  ON feishu_bot_events(sender_open_id, received_at DESC);
CREATE INDEX idx_feishu_bot_events_status
  ON feishu_bot_events(status, received_at DESC);
CREATE TABLE feishu_bot_turns (
  id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  sender_open_id TEXT NOT NULL,
  actor_name TEXT NOT NULL DEFAULT '',
  intent TEXT NOT NULL DEFAULT '',
  question TEXT NOT NULL DEFAULT '',
  response TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  FOREIGN KEY(event_id) REFERENCES feishu_bot_events(event_id) ON DELETE CASCADE
);
CREATE INDEX idx_feishu_bot_turns_context
  ON feishu_bot_turns(chat_id, sender_open_id, created_at DESC);
"""


def test_dry_run_reports_empty_legacy_tables_without_writing(tmp_path: Path) -> None:
    database_path = _create_database(tmp_path)

    result = cleanup_legacy_tables(database_path, apply=False)

    assert result["status"] == "ready"
    assert result["applied"] is False
    assert result["backupPath"] == ""
    assert _table_names(database_path) >= {
        "feishu_bot_events",
        "feishu_bot_turns",
        "resumes",
    }


def test_apply_writes_schema_backup_and_removes_only_legacy_tables(
    tmp_path: Path,
) -> None:
    database_path = _create_database(tmp_path)
    backup_dir = tmp_path / "backups"

    result = cleanup_legacy_tables(
        database_path,
        apply=True,
        backup_dir=backup_dir,
    )

    assert result["status"] == "cleaned"
    assert result["applied"] is True
    assert result["quickCheck"] == "ok"
    assert _table_names(database_path) == {"resumes"}
    backup_path = Path(result["backupPath"])
    assert backup_path.parent == backup_dir
    backup = json.loads(backup_path.read_text(encoding="utf-8"))
    assert backup["databasePath"] == str(database_path.resolve())
    assert backup["tables"]["feishu_bot_events"]["rowCount"] == 0
    assert backup["tables"]["feishu_bot_turns"]["rowCount"] == 0
    assert "CREATE TABLE feishu_bot_events" in backup["tables"]["feishu_bot_events"][
        "sql"
    ]


def test_apply_refuses_non_empty_legacy_tables(tmp_path: Path) -> None:
    database_path = _create_database(tmp_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO feishu_bot_events (
              event_id, message_id, sender_open_id, chat_id, received_at
            ) VALUES ('event-1', 'message-1', 'user-1', 'chat-1', '2026-07-16')
            """
        )

    with pytest.raises(RuntimeError, match="legacy_feishu_bot_tables_not_empty"):
        cleanup_legacy_tables(database_path, apply=True, backup_dir=tmp_path / "backup")

    assert "feishu_bot_events" in _table_names(database_path)
    assert not (tmp_path / "backup").exists()


def test_apply_refuses_unexpected_legacy_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "resumes.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE resumes (id TEXT PRIMARY KEY);
            CREATE TABLE feishu_bot_events (event_id TEXT PRIMARY KEY);
            CREATE TABLE feishu_bot_turns (id TEXT PRIMARY KEY);
            """
        )

    with pytest.raises(RuntimeError, match="legacy_feishu_bot_schema_unexpected"):
        cleanup_legacy_tables(database_path, apply=True, backup_dir=tmp_path / "backup")

    assert _table_names(database_path) == {
        "feishu_bot_events",
        "feishu_bot_turns",
        "resumes",
    }


def test_apply_refuses_matching_columns_with_changed_constraints(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "resumes.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE resumes (id TEXT PRIMARY KEY);
            CREATE TABLE feishu_bot_events (
              event_id TEXT PRIMARY KEY,
              message_id TEXT,
              sender_open_id TEXT,
              chat_id TEXT,
              chat_type TEXT,
              message_type TEXT,
              status TEXT,
              response_message_id TEXT,
              error TEXT,
              received_at TEXT,
              started_at TEXT,
              completed_at TEXT
            );
            CREATE INDEX idx_feishu_bot_events_sender
              ON feishu_bot_events(chat_id);
            CREATE INDEX idx_feishu_bot_events_status
              ON feishu_bot_events(status);
            CREATE TABLE feishu_bot_turns (
              id TEXT PRIMARY KEY,
              event_id TEXT,
              chat_id TEXT,
              sender_open_id TEXT,
              actor_name TEXT,
              intent TEXT,
              question TEXT,
              response TEXT,
              created_at TEXT
            );
            CREATE INDEX idx_feishu_bot_turns_context
              ON feishu_bot_turns(chat_id);
            """
        )

    with pytest.raises(RuntimeError, match="legacy_feishu_bot_schema_unexpected"):
        cleanup_legacy_tables(database_path, apply=True, backup_dir=tmp_path / "backup")

    assert _table_names(database_path) == {
        "feishu_bot_events",
        "feishu_bot_turns",
        "resumes",
    }


def test_apply_refuses_extra_unique_index(tmp_path: Path) -> None:
    database_path = _create_database(tmp_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE UNIQUE INDEX unexpected_feishu_bot_index
              ON feishu_bot_events(chat_id)
            """
        )

    with pytest.raises(RuntimeError, match="legacy_feishu_bot_schema_unexpected"):
        cleanup_legacy_tables(database_path, apply=True, backup_dir=tmp_path / "backup")

    assert _table_names(database_path) == {
        "feishu_bot_events",
        "feishu_bot_turns",
        "resumes",
    }


def test_apply_refuses_hidden_check_constraint(tmp_path: Path) -> None:
    database_path = tmp_path / "resumes.sqlite"
    schema = LEGACY_SCHEMA.replace(
        "received_at TEXT NOT NULL,",
        "received_at TEXT NOT NULL CHECK (length(received_at) > 0),",
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE resumes (id TEXT PRIMARY KEY)")
        connection.executescript(schema)

    with pytest.raises(RuntimeError, match="legacy_feishu_bot_schema_unexpected"):
        cleanup_legacy_tables(database_path, apply=True, backup_dir=tmp_path / "backup")

    assert "feishu_bot_events" in _table_names(database_path)


def test_apply_refuses_changed_index_collation(tmp_path: Path) -> None:
    database_path = _create_database(tmp_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP INDEX idx_feishu_bot_events_sender")
        connection.execute(
            """
            CREATE INDEX idx_feishu_bot_events_sender
              ON feishu_bot_events(sender_open_id COLLATE NOCASE, received_at DESC)
            """
        )

    with pytest.raises(RuntimeError, match="legacy_feishu_bot_schema_unexpected"):
        cleanup_legacy_tables(database_path, apply=True, backup_dir=tmp_path / "backup")

    assert "feishu_bot_events" in _table_names(database_path)


def test_apply_refuses_inbound_foreign_key_from_other_table(tmp_path: Path) -> None:
    database_path = _create_database(tmp_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE external_audit_link (
              id TEXT PRIMARY KEY,
              bot_event_id TEXT REFERENCES feishu_bot_events(event_id)
            )
            """
        )

    with pytest.raises(RuntimeError, match="legacy_feishu_bot_schema_in_use"):
        cleanup_legacy_tables(database_path, apply=True, backup_dir=tmp_path / "backup")

    assert "feishu_bot_events" in _table_names(database_path)


def test_apply_refuses_case_insensitive_fk_from_sqlite_prefixed_user_table(
    tmp_path: Path,
) -> None:
    database_path = _create_database(tmp_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE sqliteaudit (
              id TEXT PRIMARY KEY,
              bot_event_id TEXT REFERENCES FEISHU_BOT_EVENTS(event_id)
            )
            """
        )

    with pytest.raises(RuntimeError, match="legacy_feishu_bot_schema_in_use"):
        cleanup_legacy_tables(database_path, apply=True, backup_dir=tmp_path / "backup")

    assert "feishu_bot_events" in _table_names(database_path)


@pytest.mark.parametrize(
    "dependency_sql",
    [
        "CREATE VIEW external_bot_view AS SELECT * FROM FEISHU_BOT_EVENTS",
        """
        CREATE TRIGGER external_bot_trigger AFTER INSERT ON resumes
        BEGIN
          SELECT event_id FROM FEISHU_BOT_EVENTS;
        END
        """,
    ],
)
def test_apply_refuses_case_insensitive_view_or_trigger_dependency(
    tmp_path: Path,
    dependency_sql: str,
) -> None:
    database_path = _create_database(tmp_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(dependency_sql)

    with pytest.raises(RuntimeError, match="legacy_feishu_bot_schema_in_use"):
        cleanup_legacy_tables(database_path, apply=True, backup_dir=tmp_path / "backup")

    assert "feishu_bot_events" in _table_names(database_path)


def test_apply_returns_not_needed_when_transaction_recheck_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "resumes.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE resumes (id TEXT PRIMARY KEY)")
    calls = iter(({"feishu_bot_events": {}, "feishu_bot_turns": {}}, {}))
    monkeypatch.setattr(cleanup_module, "_validated_snapshot", lambda _connection: next(calls))

    result = cleanup_legacy_tables(
        database_path,
        apply=True,
        backup_dir=tmp_path / "backup",
    )

    assert result["status"] == "not_needed"
    assert result["applied"] is False
    assert not (tmp_path / "backup").exists()


def _create_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "resumes.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE resumes (id TEXT PRIMARY KEY)")
        connection.executescript(LEGACY_SCHEMA)
    return database_path


def _table_names(database_path: Path) -> set[str]:
    with sqlite3.connect(database_path) as connection:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
