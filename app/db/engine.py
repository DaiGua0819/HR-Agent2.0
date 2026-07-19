"""SQLite 连接、初始化与幂等迁移。

所有数据库路径都来自 settings 或调用方传入；验证线上库副本时，把 `DATABASE_PATH`
指向副本即可。迁移只执行幂等 DDL，不删除、不覆盖已有数据。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.settings import load_settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
MESSAGE_PROCESSING_SNAPSHOTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS message_processing_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner TEXT NOT NULL,
  platform TEXT NOT NULL,
  snapshot_key TEXT NOT NULL,
  provisional_processing_key TEXT NOT NULL,
  canonical_processing_key TEXT NOT NULL DEFAULT '',
  canonical_session_id TEXT NOT NULL DEFAULT '',
  latest_message_fingerprint TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  action TEXT NOT NULL DEFAULT '',
  stage TEXT NOT NULL DEFAULT '',
  error_reasons TEXT NOT NULL DEFAULT '[]',
  retryable INTEGER NOT NULL DEFAULT 0,
  attempt_count INTEGER NOT NULL DEFAULT 1,
  processed_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(owner, platform, snapshot_key)
)
"""


def _as_path(database_path: str | Path | None) -> Path:
    if database_path is not None:
        return Path(database_path)
    return load_settings().resolved_database_path


def connect(
    database_path: str | Path | None = None,
    *,
    read_only: bool = False,
) -> sqlite3.Connection:
    """连接 SQLite；read_only=True 用于旧库或线上副本只读巡检。"""

    path = _as_path(database_path)
    if read_only:
        uri = path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def load_schema() -> str:
    """读取当前版本建表语句。"""

    return SCHEMA_PATH.read_text(encoding="utf-8")


def initialize_database(database_path: str | Path | None = None) -> None:
    """按 schema.sql 初始化新库。"""

    with connect(database_path) as connection:
        connection.executescript(load_schema())


def run_migrations(database_path: str | Path | None = None) -> None:
    """执行幂等迁移。"""

    with connect(database_path) as connection:
        _preflight_existing_tables(connection)
        connection.commit()
    initialize_database(database_path)
    with connect(database_path) as connection:
        _add_column_if_missing(connection, "batch_items", "file_path", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(connection, "batch_items", "message", "TEXT")
        _add_column_if_missing(connection, "batch_items", "resume_id", "TEXT")
        _add_column_if_missing(connection, "resumes", "parsed_name", "TEXT")
        _add_column_if_missing(connection, "resumes", "linked_session_id", "TEXT")
        _add_column_if_missing(connection, "resumes", "linked_platform", "TEXT")
        _add_column_if_missing(connection, "resumes", "linked_owner", "TEXT")
        _add_column_if_missing(
            connection,
            "resumes",
            "linked_platform_conversation_id",
            "TEXT",
        )
        _add_column_if_missing(connection, "resumes", "source_artifact_id", "TEXT")
        _add_column_if_missing(
            connection,
            "resume_review_states",
            "user_name",
            "TEXT NOT NULL DEFAULT ''",
        )
        _add_column_if_missing(
            connection,
            "resume_review_states",
            "decision_at",
            "TEXT NOT NULL DEFAULT ''",
        )
        _add_column_if_missing(
            connection,
            "resume_review_states",
            "pushed_at",
            "TEXT NOT NULL DEFAULT ''",
        )
        _add_column_if_missing(
            connection,
            "resume_assignments",
            "completion_action",
            "TEXT NOT NULL DEFAULT ''",
        )
        _add_column_if_missing(
            connection,
            "resume_assignments",
            "completed_by_user_id",
            "TEXT NOT NULL DEFAULT ''",
        )
        _add_column_if_missing(
            connection,
            "resume_assignments",
            "completed_by_user_name",
            "TEXT NOT NULL DEFAULT ''",
        )
        _add_column_if_missing(
            connection,
            "resume_assignments",
            "completed_at",
            "TEXT NOT NULL DEFAULT ''",
        )
        _backfill_review_action_times(connection)
        _backfill_assignment_completion_actions(connection)
        _migrate_interview_sessions_if_present(connection)
        connection.commit()


def _preflight_existing_tables(connection: sqlite3.Connection) -> None:
    """先补旧表列，再执行 schema.sql 中依赖这些列的索引。"""

    tables = {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if "batch_items" in tables:
        _add_column_if_missing(connection, "batch_items", "file_path", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(connection, "batch_items", "message", "TEXT")
        _add_column_if_missing(connection, "batch_items", "resume_id", "TEXT")
    if "resumes" in tables:
        _add_column_if_missing(connection, "resumes", "parsed_name", "TEXT")
        _add_column_if_missing(connection, "resumes", "linked_session_id", "TEXT")
        _add_column_if_missing(connection, "resumes", "linked_platform", "TEXT")
        _add_column_if_missing(connection, "resumes", "linked_owner", "TEXT")
        _add_column_if_missing(
            connection,
            "resumes",
            "linked_platform_conversation_id",
            "TEXT",
        )
        _add_column_if_missing(connection, "resumes", "source_artifact_id", "TEXT")
    if "interview_sessions" in tables:
        _migrate_interview_sessions_if_present(connection)
    ensure_message_processing_snapshots_schema(connection)


def ensure_message_processing_snapshots_schema(connection: sqlite3.Connection) -> None:
    """Create or rebuild the processing snapshot table around canonical keys."""

    if not connection.in_transaction:
        connection.execute("BEGIN IMMEDIATE")
    table_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("message_processing_snapshots",),
    ).fetchone()
    if table_exists is None:
        connection.execute(MESSAGE_PROCESSING_SNAPSHOTS_TABLE_SQL)
        _create_message_processing_snapshot_index(connection)
        return
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(message_processing_snapshots)")
    }
    if "snapshot_key" in columns:
        _create_message_processing_snapshot_index(connection)
        return

    legacy_rows = connection.execute(
        "SELECT * FROM message_processing_snapshots ORDER BY updated_at, id"
    ).fetchall()
    connection.execute(
        "ALTER TABLE message_processing_snapshots "
        "RENAME TO message_processing_snapshots_legacy_v1"
    )
    connection.execute(MESSAGE_PROCESSING_SNAPSHOTS_TABLE_SQL)
    for row in legacy_rows:
        canonical_key = str(row["canonical_processing_key"] or "").strip()
        provisional_key = str(row["provisional_processing_key"] or "").strip()
        snapshot_key = canonical_key or provisional_key
        if not snapshot_key:
            continue
        connection.execute(
            """
            INSERT INTO message_processing_snapshots (
              owner, platform, snapshot_key, provisional_processing_key,
              canonical_processing_key, canonical_session_id,
              latest_message_fingerprint, status, action, stage,
              error_reasons, retryable, attempt_count, processed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner, platform, snapshot_key) DO UPDATE SET
              provisional_processing_key = excluded.provisional_processing_key,
              canonical_processing_key = CASE
                WHEN excluded.canonical_processing_key != ''
                THEN excluded.canonical_processing_key
                ELSE message_processing_snapshots.canonical_processing_key
              END,
              canonical_session_id = CASE
                WHEN excluded.canonical_session_id != ''
                THEN excluded.canonical_session_id
                ELSE message_processing_snapshots.canonical_session_id
              END,
              latest_message_fingerprint = CASE
                WHEN excluded.latest_message_fingerprint != ''
                THEN excluded.latest_message_fingerprint
                ELSE message_processing_snapshots.latest_message_fingerprint
              END,
              status = CASE
                WHEN message_processing_snapshots.status = 'completed'
                  OR excluded.status = 'completed' THEN 'completed'
                WHEN message_processing_snapshots.status = 'failed_terminal'
                  OR excluded.status = 'failed_terminal' THEN 'failed_terminal'
                ELSE 'failed_retryable'
              END,
              action = excluded.action,
              stage = excluded.stage,
              error_reasons = excluded.error_reasons,
              retryable = CASE
                WHEN message_processing_snapshots.status = 'completed'
                  OR excluded.status = 'completed'
                  OR message_processing_snapshots.status = 'failed_terminal'
                  OR excluded.status = 'failed_terminal' THEN 0
                ELSE 1
              END,
              attempt_count = message_processing_snapshots.attempt_count
                + excluded.attempt_count,
              processed_at = MIN(
                message_processing_snapshots.processed_at,
                excluded.processed_at
              ),
              updated_at = MAX(
                message_processing_snapshots.updated_at,
                excluded.updated_at
              )
            """,
            (
                row["owner"],
                row["platform"],
                snapshot_key,
                provisional_key,
                canonical_key,
                row["canonical_session_id"],
                row["latest_message_fingerprint"],
                row["status"],
                row["action"],
                row["stage"],
                row["error_reasons"],
                row["retryable"],
                row["attempt_count"],
                row["processed_at"],
                row["updated_at"],
            ),
        )
    connection.execute("DROP TABLE message_processing_snapshots_legacy_v1")
    _create_message_processing_snapshot_index(connection)


def _create_message_processing_snapshot_index(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_message_processing_snapshots_lookup
        ON message_processing_snapshots(owner, platform, status, updated_at DESC)
        """
    )


def _add_column_if_missing(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _backfill_review_action_times(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        UPDATE resume_review_states
        SET decision_at = COALESCE(
          (
            SELECT MIN(event.created_at)
            FROM resume_review_events AS event
            WHERE event.resume_id = resume_review_states.resume_id
              AND event.user_id = resume_review_states.user_id
              AND event.event_type = 'decision_changed'
          ),
          updated_at
        )
        WHERE decision_at = '' AND decision != 'undecided'
        """
    )
    connection.execute(
        """
        UPDATE resume_review_states
        SET pushed_at = COALESCE(
          (
            SELECT MIN(assignment.created_at)
            FROM resume_assignments AS assignment
            WHERE assignment.source_decision_id = resume_review_states.id
          ),
          updated_at
        )
        WHERE pushed_at = '' AND assigned_to != ''
        """
    )


def _backfill_assignment_completion_actions(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        UPDATE resume_assignments
        SET completion_action = 'review_decision'
        WHERE status = 'completed' AND completion_action = ''
        """
    )


def _migrate_interview_sessions_if_present(connection: sqlite3.Connection) -> None:
    tables = {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if "interview_sessions" not in tables:
        return
    _add_column_if_missing(connection, "interview_sessions", "feishu_event_id", "TEXT")
    _add_column_if_missing(connection, "interview_sessions", "calendar_id", "TEXT")
    _add_column_if_missing(
        connection,
        "interview_sessions",
        "start_time",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(
        connection,
        "interview_sessions",
        "end_time",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(
        connection,
        "interview_sessions",
        "question_set",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    _add_column_if_missing(
        connection,
        "interview_sessions",
        "feishu_doc",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    _add_column_if_missing(connection, "interview_sessions", "bitable_table_id", "TEXT")
    _add_column_if_missing(connection, "interview_sessions", "bitable_table_name", "TEXT")
    _add_column_if_missing(
        connection,
        "interview_sessions",
        "bitable_resume_image",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    _add_column_if_missing(
        connection,
        "interview_sessions",
        "bitable_interview_record_image",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    _add_column_if_missing(
        connection,
        "interview_sessions",
        "bitable_skill_evaluation_document",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    _add_column_if_missing(
        connection,
        "interview_sessions",
        "bitable_second_interview_evaluation_document",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    _add_column_if_missing(
        connection,
        "interview_sessions",
        "interview_evaluation",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    _add_column_if_missing(
        connection,
        "interview_sessions",
        "backfill_source",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    _add_column_if_missing(
        connection,
        "interview_sessions",
        "rule_suggestion_ids",
        "TEXT NOT NULL DEFAULT '[]'",
    )
    _add_column_if_missing(connection, "interview_sessions", "last_backfill_error", "TEXT")
    _add_column_if_missing(
        connection,
        "interview_sessions",
        "backfill_attempts",
        "INTEGER NOT NULL DEFAULT 0",
    )
