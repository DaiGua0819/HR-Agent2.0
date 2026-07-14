"""Read-only resume conversation lookup for the resume library."""

from __future__ import annotations

from typing import Any

from app.domain.conversation.models import ConversationMessageRecord, ConversationSession
from app.domain.conversation.repository import ConversationRepository
from app.domain.resume.models import Resume

MAX_CONVERSATION_MESSAGES = 200
_VALID_SENDERS = {"me", "other", "system"}


class ResumeConversationService:
    """Resolve only high-confidence resume links and expose safe message fields."""

    def __init__(self, repository: ConversationRepository) -> None:
        self.repository = repository

    def get_for_resume(
        self,
        resume: Resume,
        *,
        limit: int = MAX_CONVERSATION_MESSAGES,
    ) -> dict[str, object]:
        session = self._linked_session(resume)
        if session is None:
            reason = self._unmatched_reason(resume)
            return _empty_payload(resume, reason)

        total = self.repository.count_messages(session.id)
        bounded_limit = max(1, min(int(limit), MAX_CONVERSATION_MESSAGES))
        messages = self.repository.list_messages(session.id, limit=bounded_limit)
        return {
            "resumeId": resume.id,
            "matched": True,
            "matchMode": "linked_session_id",
            "reason": "",
            "candidate": _candidate_payload(resume),
            "conversation": _session_payload(session, total=total, limit=bounded_limit),
            "messages": [_message_payload(message) for message in messages],
        }

    def _linked_session(self, resume: Resume) -> ConversationSession | None:
        if not resume.linked_session_id:
            return None
        return self.repository.get_session(resume.linked_session_id)

    def _unmatched_reason(self, resume: Resume) -> str:
        if resume.linked_session_id:
            return "conversation_not_linked"
        name = (resume.parsed_name or resume.name or "").strip()
        position = (resume.job_type or resume.applied_position or "").strip()
        candidates = self.repository.search_by_candidate_name(
            candidate_name=name,
            position=position,
        )
        return "conversation_ambiguous" if len(candidates) > 1 else "conversation_not_linked"


def _empty_payload(resume: Resume, reason: str) -> dict[str, object]:
    return {
        "resumeId": resume.id,
        "matched": False,
        "matchMode": "none",
        "reason": reason,
        "candidate": _candidate_payload(resume),
        "conversation": None,
        "messages": [],
    }


def _candidate_payload(resume: Resume) -> dict[str, str]:
    return {
        "name": (resume.parsed_name or resume.name or "").strip(),
        "jobType": (resume.job_type or resume.applied_position or "").strip(),
    }


def _session_payload(session: ConversationSession, *, total: int, limit: int) -> dict[str, Any]:
    return {
        "sessionId": session.id,
        "platform": session.platform,
        "owner": session.owner,
        "updatedAt": session.updated_at or session.last_seen_at,
        "messageCount": total,
        "truncated": total > limit,
    }


def _message_payload(message: ConversationMessageRecord) -> dict[str, str]:
    sender = message.sender if message.sender in _VALID_SENDERS else "other"
    return {
        "id": message.id,
        "sender": sender,
        "text": message.text,
        "sentAt": message.sent_at or message.created_at,
    }
