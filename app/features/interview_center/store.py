"""面试中心会话存储。

Phase 7a 全局默认使用 SQLite `interview_sessions`；测试仍可显式注入
`InMemoryInterviewStore`。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from app.db.engine import connect, run_migrations
from app.settings import load_settings


def now_iso() -> str:
    """返回 ISO 时间。"""

    return datetime.now(UTC).isoformat()


@dataclass
class InterviewSession:
    """面试中心会话。"""

    id: str
    resume_id: str
    candidate_name: str
    job_type: str
    status: str = "created"
    questions: list[dict[str, str]] = field(default_factory=list)
    matches: list[dict[str, Any]] = field(default_factory=list)
    bitable_record_id: str = ""
    resume_image_path: str = ""
    summary_image_path: str = ""
    feedback: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 API 响应。"""

        return {
            "id": self.id,
            "resumeId": self.resume_id,
            "candidateName": self.candidate_name,
            "jobType": self.job_type,
            "status": self.status,
            "questions": self.questions,
            "matches": self.matches,
            "bitableRecordId": self.bitable_record_id,
            "resumeImagePath": self.resume_image_path,
            "summaryImagePath": self.summary_image_path,
            "feedback": self.feedback,
            "payload": self.payload,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


class InterviewStoreProtocol(Protocol):
    """面试会话存储协议。"""

    def create(
        self,
        *,
        resume_id: str,
        candidate_name: str,
        job_type: str,
        payload: dict[str, Any] | None = None,
    ) -> InterviewSession:
        """创建会话。"""

    def save(self, session: InterviewSession) -> InterviewSession:
        """保存会话。"""

    def get(self, session_id: str) -> InterviewSession | None:
        """读取会话。"""

    def list(self) -> list[InterviewSession]:
        """列出会话。"""


class InMemoryInterviewStore:
    """面试会话内存存储，供测试显式注入。"""

    def __init__(self) -> None:
        self._sessions: dict[str, InterviewSession] = {}

    def create(
        self,
        *,
        resume_id: str,
        candidate_name: str,
        job_type: str,
        payload: dict[str, Any] | None = None,
    ) -> InterviewSession:
        session = InterviewSession(
            id=str(uuid4()),
            resume_id=resume_id,
            candidate_name=candidate_name,
            job_type=job_type,
            payload=payload or {},
        )
        self._sessions[session.id] = session
        return session

    def save(self, session: InterviewSession) -> InterviewSession:
        session.updated_at = now_iso()
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> InterviewSession | None:
        return self._sessions.get(session_id)

    def list(self) -> list[InterviewSession]:
        return sorted(self._sessions.values(), key=lambda item: item.updated_at, reverse=True)

    def clear(self) -> None:
        self._sessions.clear()


class SQLiteInterviewStore:
    """面试会话 SQLite 存储。"""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = (
            Path(database_path)
            if database_path
            else load_settings().resolved_database_path
        )
        run_migrations(self.database_path)

    def create(
        self,
        *,
        resume_id: str,
        candidate_name: str,
        job_type: str,
        payload: dict[str, Any] | None = None,
    ) -> InterviewSession:
        session = InterviewSession(
            id=str(uuid4()),
            resume_id=resume_id,
            candidate_name=candidate_name,
            job_type=job_type,
            payload=payload or {},
        )
        return self.save(session)

    def save(self, session: InterviewSession) -> InterviewSession:
        session.updated_at = now_iso()
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO interview_sessions (
                  id, resume_id, candidate_name, job_type, status, questions, matches,
                  bitable_record_id, resume_image_path, summary_image_path, feedback,
                  payload, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  resume_id = excluded.resume_id,
                  candidate_name = excluded.candidate_name,
                  job_type = excluded.job_type,
                  status = excluded.status,
                  questions = excluded.questions,
                  matches = excluded.matches,
                  bitable_record_id = excluded.bitable_record_id,
                  resume_image_path = excluded.resume_image_path,
                  summary_image_path = excluded.summary_image_path,
                  feedback = excluded.feedback,
                  payload = excluded.payload,
                  updated_at = excluded.updated_at
                """,
                _session_params(session),
            )
            connection.commit()
        return session

    def get(self, session_id: str) -> InterviewSession | None:
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM interview_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return _session_from_row(row) if row else None

    def list(self) -> list[InterviewSession]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT * FROM interview_sessions ORDER BY updated_at DESC"
            ).fetchall()
        return [_session_from_row(row) for row in rows]

    def clear(self) -> None:
        with connect(self.database_path) as connection:
            connection.execute("DELETE FROM interview_sessions")
            connection.commit()


GLOBAL_INTERVIEW_STORE = SQLiteInterviewStore()


def save_interview_session(session: dict[str, Any]) -> None:
    """兼容旧入口，保存面试会话到 SQLite。"""

    model = InterviewSession(
        id=str(session.get("id") or uuid4()),
        resume_id=str(session.get("resumeId") or session.get("resume_id") or ""),
        candidate_name=str(session.get("candidateName") or session.get("name") or ""),
        job_type=str(session.get("jobType") or session.get("position") or ""),
        status=str(session.get("status") or "created"),
        questions=list(session.get("questions") or []),
        payload=dict(session),
    )
    GLOBAL_INTERVIEW_STORE.save(model)


def _session_params(session: InterviewSession) -> tuple[Any, ...]:
    return (
        session.id,
        session.resume_id,
        session.candidate_name,
        session.job_type,
        session.status,
        json.dumps(session.questions, ensure_ascii=False, sort_keys=True),
        json.dumps(session.matches, ensure_ascii=False, sort_keys=True),
        session.bitable_record_id,
        session.resume_image_path,
        session.summary_image_path,
        session.feedback,
        json.dumps(session.payload, ensure_ascii=False, sort_keys=True),
        session.created_at,
        session.updated_at,
    )


def _session_from_row(row: Any) -> InterviewSession:
    return InterviewSession(
        id=row["id"],
        resume_id=row["resume_id"],
        candidate_name=row["candidate_name"] or "",
        job_type=row["job_type"] or "",
        status=row["status"],
        questions=json.loads(row["questions"]),
        matches=json.loads(row["matches"]),
        bitable_record_id=row["bitable_record_id"] or "",
        resume_image_path=row["resume_image_path"] or "",
        summary_image_path=row["summary_image_path"] or "",
        feedback=row["feedback"] or "",
        payload=json.loads(row["payload"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
