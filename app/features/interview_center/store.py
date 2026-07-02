"""Interview center session storage.

The current service stores interview-center state in SQLite. This module keeps the
Phase 6 lightweight API intact while adding the old interview-center persistence
surface: Feishu calendar event upsert, OAuth token storage, and session logs.
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
    """Return an ISO timestamp."""

    return datetime.now(UTC).isoformat()


@dataclass
class InterviewSession:
    """Interview-center session.

    New fields mirror the old Node interview center payload. Existing lightweight
    fields remain first-class so older tests and callers keep working.
    """

    id: str
    resume_id: str
    candidate_name: str
    job_type: str
    feishu_event_id: str = ""
    calendar_id: str = ""
    status: str = "created"
    start_time: int = 0
    end_time: int = 0
    questions: list[dict[str, str]] = field(default_factory=list)
    question_set: dict[str, Any] = field(default_factory=dict)
    matches: list[dict[str, Any]] = field(default_factory=list)
    feishu_doc: dict[str, Any] = field(default_factory=dict)
    bitable_record_id: str = ""
    bitable_table_id: str = ""
    bitable_table_name: str = ""
    bitable_resume_image: dict[str, Any] = field(default_factory=dict)
    bitable_interview_record_image: dict[str, Any] = field(default_factory=dict)
    bitable_skill_evaluation_document: dict[str, Any] = field(default_factory=dict)
    bitable_second_interview_evaluation_document: dict[str, Any] = field(default_factory=dict)
    resume_image_path: str = ""
    summary_image_path: str = ""
    feedback: str = ""
    interview_evaluation: dict[str, Any] = field(default_factory=dict)
    backfill_source: dict[str, Any] = field(default_factory=dict)
    rule_suggestion_ids: list[str] = field(default_factory=list)
    last_backfill_error: str = ""
    backfill_attempts: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API responses."""

        return {
            "id": self.id,
            "feishuEventId": self.feishu_event_id,
            "calendarId": self.calendar_id,
            "resumeId": self.resume_id,
            "candidateName": self.candidate_name,
            "jobType": self.job_type,
            "status": self.status,
            "startTime": self.start_time,
            "endTime": self.end_time,
            "questions": self.questions,
            "questionSet": self.question_set,
            "matches": self.matches,
            "feishuDoc": self.feishu_doc,
            "bitableRecordId": self.bitable_record_id,
            "bitableTableId": self.bitable_table_id,
            "bitableTableName": self.bitable_table_name,
            "bitableResumeImage": self.bitable_resume_image,
            "bitableInterviewRecordImage": self.bitable_interview_record_image,
            "bitableSkillEvaluationDocument": self.bitable_skill_evaluation_document,
            "bitableSecondInterviewEvaluationDocument": (
                self.bitable_second_interview_evaluation_document
            ),
            "resumeImagePath": self.resume_image_path,
            "summaryImagePath": self.summary_image_path,
            "feedback": self.feedback,
            "interviewEvaluation": self.interview_evaluation,
            "humanReview": self.payload.get("humanReview") or {},
            "backfillSource": self.backfill_source,
            "ruleSuggestionIds": self.rule_suggestion_ids,
            "lastBackfillError": self.last_backfill_error,
            "backfillAttempts": self.backfill_attempts,
            "payload": self.payload,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


class InterviewStoreProtocol(Protocol):
    """Interview session storage protocol."""

    def create(
        self,
        *,
        resume_id: str,
        candidate_name: str,
        job_type: str,
        payload: dict[str, Any] | None = None,
    ) -> InterviewSession:
        """Create a session."""

    def save(self, session: InterviewSession) -> InterviewSession:
        """Save a session."""

    def upsert_from_calendar_event(self, event: dict[str, Any]) -> InterviewSession:
        """Create or update a session from a Feishu calendar event."""

    def get(self, session_id: str) -> InterviewSession | None:
        """Load a session."""

    def list(self) -> list[InterviewSession]:
        """List sessions."""


class InMemoryInterviewStore:
    """In-memory interview store for tests."""

    def __init__(self) -> None:
        self._sessions: dict[str, InterviewSession] = {}
        self._token: dict[str, Any] | None = None
        self._logs: list[dict[str, Any]] = []

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

    def upsert_from_calendar_event(self, event: dict[str, Any]) -> InterviewSession:
        feishu_event_id = _event_text(event, "feishuEventId", "event_id")
        existing = next(
            (
                session
                for session in self._sessions.values()
                if session.feishu_event_id == feishu_event_id
            ),
            None,
        )
        session = _session_from_event(event, existing=existing)
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> InterviewSession | None:
        return self._sessions.get(session_id)

    def list(self) -> list[InterviewSession]:
        return sorted(self._sessions.values(), key=lambda item: item.updated_at, reverse=True)

    def clear(self) -> None:
        self._sessions.clear()
        self._logs.clear()
        self._token = None

    def save_token(self, token: dict[str, Any]) -> None:
        self._token = dict(token)

    def get_token(self) -> dict[str, Any] | None:
        return dict(self._token) if self._token is not None else None

    def clear_token(self) -> None:
        self._token = None

    def append_log(
        self,
        session_id: str,
        level: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._logs.append(
            {
                "id": str(uuid4()),
                "sessionId": session_id,
                "level": level or "info",
                "message": message,
                "payload": payload or {},
                "createdAt": now_iso(),
            }
        )

    def list_logs(self, session_id: str = "", limit: int = 80) -> list[dict[str, Any]]:
        logs = [item for item in self._logs if not session_id or item["sessionId"] == session_id]
        return sorted(logs, key=lambda item: item["createdAt"], reverse=True)[:limit]


class SQLiteInterviewStore:
    """SQLite-backed interview store."""

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
                  id, feishu_event_id, calendar_id, resume_id, candidate_name, job_type,
                  status, start_time, end_time, questions, question_set, matches,
                  feishu_doc, bitable_record_id, bitable_table_id, bitable_table_name,
                  bitable_resume_image, bitable_interview_record_image,
                  bitable_skill_evaluation_document,
                  bitable_second_interview_evaluation_document, resume_image_path,
                  summary_image_path, feedback, interview_evaluation, backfill_source,
                  rule_suggestion_ids, last_backfill_error, backfill_attempts, payload,
                  created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(id) DO UPDATE SET
                  feishu_event_id = excluded.feishu_event_id,
                  calendar_id = excluded.calendar_id,
                  resume_id = excluded.resume_id,
                  candidate_name = excluded.candidate_name,
                  job_type = excluded.job_type,
                  status = excluded.status,
                  start_time = excluded.start_time,
                  end_time = excluded.end_time,
                  questions = excluded.questions,
                  question_set = excluded.question_set,
                  matches = excluded.matches,
                  feishu_doc = excluded.feishu_doc,
                  bitable_record_id = excluded.bitable_record_id,
                  bitable_table_id = excluded.bitable_table_id,
                  bitable_table_name = excluded.bitable_table_name,
                  bitable_resume_image = excluded.bitable_resume_image,
                  bitable_interview_record_image = excluded.bitable_interview_record_image,
                  bitable_skill_evaluation_document = excluded.bitable_skill_evaluation_document,
                  bitable_second_interview_evaluation_document =
                    excluded.bitable_second_interview_evaluation_document,
                  resume_image_path = excluded.resume_image_path,
                  summary_image_path = excluded.summary_image_path,
                  feedback = excluded.feedback,
                  interview_evaluation = excluded.interview_evaluation,
                  backfill_source = excluded.backfill_source,
                  rule_suggestion_ids = excluded.rule_suggestion_ids,
                  last_backfill_error = excluded.last_backfill_error,
                  backfill_attempts = excluded.backfill_attempts,
                  payload = excluded.payload,
                  updated_at = excluded.updated_at
                """,
                _session_params(session),
            )
            connection.commit()
        return session

    def upsert_from_calendar_event(self, event: dict[str, Any]) -> InterviewSession:
        existing = self.get_by_feishu_event_id(_event_text(event, "feishuEventId", "event_id"))
        return self.save(_session_from_event(event, existing=existing))

    def get_by_feishu_event_id(self, feishu_event_id: str) -> InterviewSession | None:
        if not feishu_event_id:
            return None
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM interview_sessions WHERE feishu_event_id = ?",
                (feishu_event_id,),
            ).fetchone()
        return _session_from_row(row) if row else None

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

    def save_token(self, token: dict[str, Any]) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO interview_feishu_tokens (id, payload, updated_at)
                VALUES ('default', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  payload = excluded.payload,
                  updated_at = excluded.updated_at
                """,
                (_json_dumps(token), now_iso()),
            )
            connection.commit()

    def get_token(self) -> dict[str, Any] | None:
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT payload FROM interview_feishu_tokens WHERE id = 'default'"
            ).fetchone()
        return _json_loads(row["payload"], {}) if row else None

    def clear_token(self) -> None:
        with connect(self.database_path) as connection:
            connection.execute("DELETE FROM interview_feishu_tokens WHERE id = 'default'")
            connection.commit()

    def append_log(
        self,
        session_id: str,
        level: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO interview_logs (id, session_id, level, message, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    session_id,
                    level or "info",
                    message,
                    _json_dumps(payload or {}),
                    now_iso(),
                ),
            )
            connection.commit()

    def list_logs(self, session_id: str = "", limit: int = 80) -> list[dict[str, Any]]:
        if session_id:
            sql = (
                "SELECT * FROM interview_logs WHERE session_id = ? "
                "ORDER BY created_at DESC LIMIT ?"
            )
            params: tuple[Any, ...] = (session_id, int(limit))
        else:
            sql = "SELECT * FROM interview_logs ORDER BY created_at DESC LIMIT ?"
            params = (int(limit),)
        with connect(self.database_path) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [
            {
                "id": row["id"],
                "sessionId": row["session_id"] or "",
                "level": row["level"],
                "message": row["message"],
                "payload": _json_loads(row["payload"], {}),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]


GLOBAL_INTERVIEW_STORE = SQLiteInterviewStore()


def save_interview_session(session: dict[str, Any]) -> None:
    """Compatibility entry point for saving interview sessions to SQLite."""

    model = InterviewSession(
        id=str(session.get("id") or uuid4()),
        resume_id=str(session.get("resumeId") or session.get("resume_id") or ""),
        candidate_name=str(session.get("candidateName") or session.get("name") or ""),
        job_type=str(session.get("jobType") or session.get("position") or ""),
        status=str(session.get("status") or "created"),
        questions=list(session.get("questions") or []),
        question_set=dict(session.get("questionSet") or {}),
        payload=dict(session),
    )
    GLOBAL_INTERVIEW_STORE.save(model)


def _session_params(session: InterviewSession) -> tuple[Any, ...]:
    return (
        session.id,
        session.feishu_event_id,
        session.calendar_id,
        session.resume_id,
        session.candidate_name,
        session.job_type,
        session.status,
        int(session.start_time or 0),
        int(session.end_time or 0),
        _json_dumps(session.questions),
        _json_dumps(session.question_set),
        _json_dumps(session.matches),
        _json_dumps(session.feishu_doc),
        session.bitable_record_id,
        session.bitable_table_id,
        session.bitable_table_name,
        _json_dumps(session.bitable_resume_image),
        _json_dumps(session.bitable_interview_record_image),
        _json_dumps(session.bitable_skill_evaluation_document),
        _json_dumps(session.bitable_second_interview_evaluation_document),
        session.resume_image_path,
        session.summary_image_path,
        session.feedback,
        _json_dumps(session.interview_evaluation),
        _json_dumps(session.backfill_source),
        _json_dumps(session.rule_suggestion_ids),
        session.last_backfill_error,
        int(session.backfill_attempts or 0),
        _json_dumps(session.payload),
        session.created_at,
        session.updated_at,
    )


def _session_from_row(row: Any) -> InterviewSession:
    return InterviewSession(
        id=row["id"],
        feishu_event_id=row["feishu_event_id"] or "",
        calendar_id=row["calendar_id"] or "",
        resume_id=row["resume_id"],
        candidate_name=row["candidate_name"] or "",
        job_type=row["job_type"] or "",
        status=row["status"],
        start_time=int(row["start_time"] or 0),
        end_time=int(row["end_time"] or 0),
        questions=_json_loads(row["questions"], []),
        question_set=_json_loads(row["question_set"], {}),
        matches=_json_loads(row["matches"], []),
        feishu_doc=_json_loads(row["feishu_doc"], {}),
        bitable_record_id=row["bitable_record_id"] or "",
        bitable_table_id=row["bitable_table_id"] or "",
        bitable_table_name=row["bitable_table_name"] or "",
        bitable_resume_image=_json_loads(row["bitable_resume_image"], {}),
        bitable_interview_record_image=_json_loads(row["bitable_interview_record_image"], {}),
        bitable_skill_evaluation_document=_json_loads(
            row["bitable_skill_evaluation_document"],
            {},
        ),
        bitable_second_interview_evaluation_document=_json_loads(
            row["bitable_second_interview_evaluation_document"],
            {},
        ),
        resume_image_path=row["resume_image_path"] or "",
        summary_image_path=row["summary_image_path"] or "",
        feedback=row["feedback"] or "",
        interview_evaluation=_json_loads(row["interview_evaluation"], {}),
        backfill_source=_json_loads(row["backfill_source"], {}),
        rule_suggestion_ids=_json_loads(row["rule_suggestion_ids"], []),
        last_backfill_error=row["last_backfill_error"] or "",
        backfill_attempts=int(row["backfill_attempts"] or 0),
        payload=_json_loads(row["payload"], {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _session_from_event(
    event: dict[str, Any],
    *,
    existing: InterviewSession | None = None,
) -> InterviewSession:
    payload = {**(existing.payload if existing else {}), **event}
    status = str(event.get("status") or "synced")
    if existing and existing.status not in {"", "synced"}:
        status = existing.status
    return InterviewSession(
        id=existing.id if existing else str(uuid4()),
        feishu_event_id=_event_text(event, "feishuEventId", "event_id"),
        calendar_id=_event_text(event, "calendarId", "calendar_id"),
        resume_id=_event_text(event, "resumeId", "resume_id")
        or (existing.resume_id if existing else ""),
        candidate_name=_event_text(event, "candidateName", "candidate_name")
        or (existing.candidate_name if existing else ""),
        job_type=_event_text(event, "jobType", "job_type", "position")
        or (existing.job_type if existing else ""),
        status=status,
        start_time=_event_int(event, "startTime", "start_time"),
        end_time=_event_int(event, "endTime", "end_time"),
        questions=list(existing.questions if existing else []),
        question_set=dict(existing.question_set if existing else {}),
        matches=list(existing.matches if existing else []),
        feishu_doc=dict(existing.feishu_doc if existing else {}),
        bitable_record_id=existing.bitable_record_id if existing else "",
        bitable_table_id=existing.bitable_table_id if existing else "",
        bitable_table_name=existing.bitable_table_name if existing else "",
        bitable_resume_image=dict(existing.bitable_resume_image if existing else {}),
        bitable_interview_record_image=dict(
            existing.bitable_interview_record_image if existing else {}
        ),
        bitable_skill_evaluation_document=dict(
            existing.bitable_skill_evaluation_document if existing else {}
        ),
        bitable_second_interview_evaluation_document=dict(
            existing.bitable_second_interview_evaluation_document if existing else {}
        ),
        resume_image_path=existing.resume_image_path if existing else "",
        summary_image_path=existing.summary_image_path if existing else "",
        feedback=existing.feedback if existing else "",
        interview_evaluation=dict(existing.interview_evaluation if existing else {}),
        backfill_source=dict(existing.backfill_source if existing else {}),
        rule_suggestion_ids=list(existing.rule_suggestion_ids if existing else []),
        last_backfill_error=existing.last_backfill_error if existing else "",
        backfill_attempts=existing.backfill_attempts if existing else 0,
        payload=payload,
        created_at=existing.created_at if existing else now_iso(),
        updated_at=now_iso(),
    )


def _event_text(event: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = event.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _event_int(event: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = event.get(key)
        if value not in (None, ""):
            return int(value)
    return 0


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback
