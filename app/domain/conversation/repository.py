"""候选人会话状态 SQLite 仓储。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.db.engine import connect, run_migrations
from app.domain.conversation.dedup import message_hash, recent_messages_fingerprint
from app.domain.conversation.models import (
    CandidateStatus,
    ConversationMessageRecord,
    ConversationSession,
)
from app.platforms.types import ChatMessage
from app.settings import AppSettings, load_settings


class ConversationRepository:
    """读写会话身份、消息和候选人长期状态。"""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        run_migrations(self.database_path)

    @classmethod
    def from_settings(cls, settings: AppSettings | None = None) -> ConversationRepository:
        """从配置创建仓储。"""

        resolved = settings or load_settings()
        return cls(resolved.resolved_database_path)

    def get_session(self, session_id: str) -> ConversationSession | None:
        """按主键读取 session。"""

        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM conversation_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return _session_from_row(row) if row else None

    def find_by_platform_identity(
        self,
        *,
        platform: str,
        owner: str,
        platform_conversation_id: str,
        position: str,
    ) -> ConversationSession | None:
        """按平台 ID + 岗位定位会话。"""

        if not platform_conversation_id:
            return None
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT * FROM conversation_sessions
                WHERE platform = ? AND owner = ?
                  AND platform_conversation_id = ? AND position = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (platform, owner, platform_conversation_id, position),
            ).fetchone()
        return _session_from_row(row) if row else None

    def find_candidate_sessions(
        self,
        *,
        platform: str,
        owner: str,
        candidate_name: str,
        position: str,
    ) -> list[ConversationSession]:
        """按候选人显示名和岗位查找兜底候选 session。"""

        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM conversation_sessions
                WHERE platform = ? AND owner = ? AND candidate_name = ? AND position = ?
                ORDER BY updated_at DESC
                """,
                (platform, owner, candidate_name, position),
            ).fetchall()
        return [_session_from_row(row) for row in rows]

    def search_by_candidate_name(
        self,
        *,
        candidate_name: str,
        position: str = "",
    ) -> list[ConversationSession]:
        """Search historical sessions by parsed resume name and optional job."""

        if not candidate_name.strip():
            return []
        params: list[Any] = [candidate_name.strip()]
        position_clause = ""
        if position.strip():
            position_clause = " AND position = ?"
            params.append(position.strip())
        with connect(self.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM conversation_sessions
                WHERE candidate_name = ?{position_clause}
                ORDER BY updated_at DESC
                """,
                tuple(params),
            ).fetchall()
        return [_session_from_row(row) for row in rows]

    def save_session(self, session: ConversationSession) -> ConversationSession:
        """插入或更新 session。"""

        now = _now_iso()
        created_at = session.created_at or now
        updated = ConversationSession(
            **{
                **session.__dict__,
                "created_at": created_at,
                "updated_at": now,
                "last_seen_at": now,
            }
        )
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO conversation_sessions (
                  id, platform, owner, candidate_name, position, applied_position,
                  platform_conversation_id, label, current_stage, next_action,
                  recent_messages_fingerprint, identity_confidence, identity_warnings,
                  last_seen_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  candidate_name = excluded.candidate_name,
                  position = excluded.position,
                  applied_position = excluded.applied_position,
                  platform_conversation_id = excluded.platform_conversation_id,
                  label = excluded.label,
                  recent_messages_fingerprint = excluded.recent_messages_fingerprint,
                  identity_confidence = excluded.identity_confidence,
                  identity_warnings = excluded.identity_warnings,
                  last_seen_at = excluded.last_seen_at,
                  updated_at = excluded.updated_at
                """,
                _session_params(updated),
            )
            connection.commit()
        return updated

    def update_recent_fingerprint(
        self,
        session_id: str,
        messages: list[ChatMessage],
    ) -> str:
        """更新最近消息指纹并返回新指纹。"""

        fingerprint = recent_messages_fingerprint(messages)
        now = _now_iso()
        with connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE conversation_sessions
                SET recent_messages_fingerprint = ?, last_seen_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (fingerprint, now, now, session_id),
            )
            connection.commit()
        return fingerprint

    def update_session_progress(
        self,
        session_id: str,
        *,
        current_stage: str,
        next_action: str,
    ) -> None:
        """保存当前处理阶段和下一步动作。"""

        now = _now_iso()
        with connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE conversation_sessions
                SET current_stage = ?, next_action = ?, updated_at = ?
                WHERE id = ?
                """,
                (current_stage, next_action, now, session_id),
            )
            connection.commit()

    def upsert_messages(
        self,
        session_id: str,
        messages: list[ChatMessage],
    ) -> list[ConversationMessageRecord]:
        """按消息哈希去重写入当前页面消息。"""

        now = _now_iso()
        records: list[ConversationMessageRecord] = []
        with connect(self.database_path) as connection:
            for index, message in enumerate(messages):
                digest = message_hash(message, sequence=index)
                record = ConversationMessageRecord(
                    id=str(uuid4()),
                    session_id=session_id,
                    sender=str(message.sender.value),
                    text=message.text,
                    raw_text=message.raw_text or message.text,
                    sent_at=message.time,
                    platform_message_id="",
                    message_hash=digest,
                    created_at=now,
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO conversation_messages (
                      id, session_id, sender, text, raw_text, sent_at,
                      platform_message_id, message_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.id,
                        record.session_id,
                        record.sender,
                        record.text,
                        record.raw_text,
                        record.sent_at,
                        record.platform_message_id,
                        record.message_hash,
                        record.created_at,
                    ),
                )
                records.append(record)
            connection.commit()
        return records

    def get_status(self, session_id: str) -> CandidateStatus:
        """读取候选人状态；不存在时返回空状态。"""

        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM candidate_status WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return _status_from_row(row) if row else CandidateStatus(session_id=session_id)

    def save_status(self, status: CandidateStatus) -> CandidateStatus:
        """插入或更新候选人状态。"""

        updated = CandidateStatus(**{**status.__dict__, "updated_at": _now_iso()})
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO candidate_status (
                  session_id, asked_questions, resume_requested, resume_received,
                  resume_downloaded, resume_path, last_action, next_question,
                  decided_result, payload, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  asked_questions = excluded.asked_questions,
                  resume_requested = excluded.resume_requested,
                  resume_received = excluded.resume_received,
                  resume_downloaded = excluded.resume_downloaded,
                  resume_path = excluded.resume_path,
                  last_action = excluded.last_action,
                  next_question = excluded.next_question,
                  decided_result = excluded.decided_result,
                  payload = excluded.payload,
                  updated_at = excluded.updated_at
                """,
                _status_params(updated),
            )
            connection.commit()
        return updated


def _session_params(session: ConversationSession) -> tuple[Any, ...]:
    return (
        session.id,
        session.platform,
        session.owner,
        session.candidate_name,
        session.position,
        session.applied_position,
        session.platform_conversation_id,
        session.label,
        session.current_stage,
        session.next_action,
        session.recent_messages_fingerprint,
        session.identity_confidence,
        json.dumps(session.identity_warnings, ensure_ascii=False),
        session.last_seen_at,
        session.created_at,
        session.updated_at,
    )


def _status_params(status: CandidateStatus) -> tuple[Any, ...]:
    return (
        status.session_id,
        json.dumps(status.asked_questions, ensure_ascii=False),
        1 if status.resume_requested else 0,
        1 if status.resume_received else 0,
        1 if status.resume_downloaded else 0,
        status.resume_path,
        status.last_action,
        status.next_question,
        status.decided_result,
        json.dumps(status.payload, ensure_ascii=False, sort_keys=True),
        status.updated_at,
    )


def _session_from_row(row: Any) -> ConversationSession:
    return ConversationSession(
        id=row["id"],
        platform=row["platform"],
        owner=row["owner"],
        candidate_name=row["candidate_name"],
        position=row["position"],
        applied_position=row["applied_position"],
        platform_conversation_id=row["platform_conversation_id"],
        label=row["label"],
        current_stage=row["current_stage"],
        next_action=row["next_action"],
        recent_messages_fingerprint=row["recent_messages_fingerprint"],
        identity_confidence=row["identity_confidence"],
        identity_warnings=_json_list(row["identity_warnings"]),
        last_seen_at=row["last_seen_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _status_from_row(row: Any) -> CandidateStatus:
    return CandidateStatus(
        session_id=row["session_id"],
        asked_questions=_json_list(row["asked_questions"]),
        resume_requested=bool(row["resume_requested"]),
        resume_received=bool(row["resume_received"]),
        resume_downloaded=bool(row["resume_downloaded"]),
        resume_path=row["resume_path"],
        last_action=row["last_action"],
        next_question=row["next_question"],
        decided_result=row["decided_result"],
        payload=_json_dict(row["payload"]),
        updated_at=row["updated_at"],
    )


def _json_list(value: str) -> list[str]:
    try:
        data = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


def _json_dict(value: str) -> dict[str, object]:
    try:
        data = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
