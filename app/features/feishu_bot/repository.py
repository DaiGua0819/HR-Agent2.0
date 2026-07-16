"""Idempotency and audit persistence for the Feishu read-only bot."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.features.feishu_bot.models import BotEvent

_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_CREDENTIAL_RE = re.compile(
    r"(?i)\b(access[_-]?token|app[_-]?secret|authorization|cookie)\s*[:=]\s*[^\s,;]+"
)

_BOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS feishu_bot_events (
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
CREATE INDEX IF NOT EXISTS idx_feishu_bot_events_sender
  ON feishu_bot_events(sender_open_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_feishu_bot_events_status
  ON feishu_bot_events(status, received_at DESC);

CREATE TABLE IF NOT EXISTS feishu_bot_turns (
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
CREATE INDEX IF NOT EXISTS idx_feishu_bot_turns_context
  ON feishu_bot_turns(chat_id, sender_open_id, created_at DESC);
"""


class FeishuBotRepository:
    """Store bot-only events without modifying recruitment business rows."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_BOT_SCHEMA)

    def claim_event(self, event: BotEvent) -> bool:
        event.validate_required()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO feishu_bot_events (
                  event_id, message_id, sender_open_id, chat_id, chat_type,
                  message_type, status, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'received', ?)
                """,
                (
                    event.event_id,
                    event.message_id,
                    event.sender_open_id,
                    event.chat_id,
                    event.chat_type,
                    event.message_type,
                    _now_iso(),
                ),
            )
            connection.commit()
            return cursor.rowcount == 1

    def mark_processing(self, event_id: str) -> None:
        self._update_event(
            event_id,
            "status = 'processing', started_at = ?, error = ''",
            (_now_iso(),),
        )

    def mark_completed(self, event_id: str, *, response_message_id: str = "") -> None:
        self._update_event(
            event_id,
            "status = 'completed', response_message_id = ?, completed_at = ?, error = ''",
            (response_message_id, _now_iso()),
        )

    def mark_failed(self, event_id: str, error: str, *, status: str = "failed") -> None:
        self._update_event(
            event_id,
            "status = ?, error = ?, completed_at = ?",
            (status, _bounded(redact_sensitive_text(error), 1000), _now_iso()),
        )

    def get_event(self, event_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM feishu_bot_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def append_turn(
        self,
        *,
        event_id: str,
        chat_id: str,
        sender_open_id: str,
        actor_name: str,
        intent: str,
        question: str,
        response: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO feishu_bot_turns (
                  id, event_id, chat_id, sender_open_id, actor_name,
                  intent, question, response, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    event_id,
                    chat_id,
                    sender_open_id,
                    _bounded(redact_sensitive_text(actor_name), 100),
                    _bounded(intent, 64),
                    _bounded(redact_sensitive_text(question), 1000),
                    _bounded(redact_sensitive_text(response), 4000),
                    _now_iso(),
                ),
            )
            connection.commit()

    def recent_turns(
        self,
        chat_id: str,
        sender_open_id: str,
        *,
        limit: int = 6,
    ) -> list[dict[str, object]]:
        bounded_limit = max(1, min(int(limit), 20))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM (
                  SELECT rowid AS turn_rowid, *
                  FROM feishu_bot_turns
                  WHERE chat_id = ? AND sender_open_id = ?
                  ORDER BY created_at DESC, rowid DESC
                  LIMIT ?
                )
                ORDER BY created_at, turn_rowid
                """,
                (chat_id, sender_open_id, bounded_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def _update_event(
        self,
        event_id: str,
        assignments: str,
        params: tuple[object, ...],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                f"UPDATE feishu_bot_events SET {assignments} WHERE event_id = ?",
                (*params, event_id),
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def redact_sensitive_text(value: object) -> str:
    text = str(value or "")
    text = _PHONE_RE.sub("[手机号]", text)
    text = _EMAIL_RE.sub("[邮箱]", text)
    return _CREDENTIAL_RE.sub(lambda match: f"{match.group(1)}=[敏感凭据]", text)


def _bounded(value: object, limit: int) -> str:
    return str(value or "")[:limit]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
