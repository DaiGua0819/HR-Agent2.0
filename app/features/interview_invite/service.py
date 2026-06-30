"""Build and dispatch resume-library interview invite requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.constants import Platform
from app.domain.conversation.models import ConversationSession
from app.domain.conversation.repository import ConversationRepository
from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository


@dataclass(frozen=True)
class InterviewInviteError(Exception):
    """Controlled invite workflow failure."""

    reason: str
    message: str = ""

    def __str__(self) -> str:
        return self.message or self.reason


class InterviewInviteService:
    """Resolve resume identity and dispatch platform interview invite actions."""

    def __init__(
        self,
        *,
        resume_repository: ResumeRepository,
        conversation_repository: ConversationRepository,
        dispatcher: Any,
    ) -> None:
        self.resume_repository = resume_repository
        self.conversation_repository = conversation_repository
        self.dispatcher = dispatcher

    async def invite(
        self,
        resume_id: str,
        *,
        dry_run: bool = True,
        confirm_live: bool = False,
        selected_session_id: str = "",
    ) -> dict[str, Any]:
        """Resolve a resume to a platform session and dispatch the invite."""

        if not dry_run and not confirm_live:
            raise InterviewInviteError(
                "live_confirmation_required",
                "非 dry-run 约面试必须显式 confirmLive=true",
            )
        resume = self._load_resume(resume_id)
        if resume is None:
            raise InterviewInviteError("resume_not_found", "简历不存在")
        session = self._resolve_session(resume, selected_session_id=selected_session_id)
        if session is None:
            return self._confirmation_required(resume)
        platform = self._platform(session.platform)
        contact = self._platform_contact(session)
        if not contact["displayName"]:
            raise InterviewInviteError(
                "missing_platform_display_name",
                "缺少平台联系人显示名",
            )
        payload = {
            "platform": platform.value,
            "owner": session.owner,
            "sourceSessionId": session.id,
            "platformConversationId": session.platform_conversation_id,
            "action": "exchange_wechat",
            "dryRun": dry_run,
            "confirmLive": confirm_live,
            "platformContact": contact,
        }
        dispatched = await self.dispatcher.interview_invite(session.owner, payload)
        worker_result = dict(getattr(dispatched, "result", dispatched) or {})
        return {
            "accepted": bool(worker_result.get("accepted", True)),
            "dryRun": dry_run,
            "owner": session.owner,
            "platform": platform.value,
            "resumeId": resume.id,
            "sourceSessionId": session.id,
            "platformContact": contact,
            "workerResult": worker_result,
            **worker_result,
        }

    def _load_resume(self, resume_id: str) -> Resume | None:
        record = self.resume_repository.get(resume_id)
        return Resume.from_record(record) if record else None

    def _resolve_session(
        self,
        resume: Resume,
        *,
        selected_session_id: str = "",
    ) -> ConversationSession | None:
        if selected_session_id:
            return self.conversation_repository.get_session(selected_session_id)
        if resume.linked_session_id:
            return self.conversation_repository.get_session(resume.linked_session_id)
        return None

    def _confirmation_required(self, resume: Resume) -> dict[str, Any]:
        name = resume.parsed_name or resume.name or ""
        position = resume.job_type or resume.applied_position or ""
        candidates = self.conversation_repository.search_by_candidate_name(
            candidate_name=name,
            position=position,
        )
        return {
            "accepted": False,
            "dryRun": True,
            "resumeId": resume.id,
            "reason": "missing_linked_session",
            "requiresConfirmation": True,
            "candidates": [_session_payload(session) for session in candidates],
        }

    def _platform_contact(self, session: ConversationSession) -> dict[str, Any]:
        messages = self.conversation_repository.list_messages(session.id, limit=3)
        return {
            "displayName": session.candidate_name,
            "label": session.label,
            "appliedPosition": session.applied_position or session.position,
            "chatEvidence": [
                {"sender": item.sender, "text": item.text, "time": item.sent_at}
                for item in messages
                if item.text
            ],
        }

    @staticmethod
    def _platform(value: str) -> Platform:
        try:
            return Platform(value)
        except ValueError as exc:
            raise InterviewInviteError("unsupported_source", "不支持的平台来源") from exc


def _session_payload(session: ConversationSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "platform": session.platform,
        "owner": session.owner,
        "platformConversationId": session.platform_conversation_id,
        "candidateName": session.candidate_name,
        "position": session.position,
        "label": session.label,
    }

