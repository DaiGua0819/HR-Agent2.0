"""面试中心编排服务。

移植旧 `index.js` 的主流程：简历/会话上下文 → 候选人匹配 → LLM 出题 → 飞书多维表同步
→ 出图 → 会话状态更新。所有外部集成走可 mock 接口。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.domain.conversation.models import ConversationSession
from app.domain.conversation.repository import ConversationRepository
from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository
from app.features.interview_center.candidate_matcher import match_candidates
from app.features.interview_center.feedback_backfill import FeedbackBackfillService
from app.features.interview_center.feishu.assets import (
    BITABLE_TABLES,
    CandidateFields,
    SessionFields,
)
from app.features.interview_center.feishu.bitable import (
    BitableClientProtocol,
    MockFeishuBitableClient,
)
from app.features.interview_center.feishu.oauth import FeishuOAuthService
from app.features.interview_center.question_generator import (
    InterviewQuestionGenerator,
    QuestionLLMProtocol,
)
from app.features.interview_center.render_resume_image import render_resume_image
from app.features.interview_center.render_summary_image import render_summary_image
from app.features.interview_center.store import (
    GLOBAL_INTERVIEW_STORE,
    InterviewSession,
    InterviewStoreProtocol,
)
from app.llm.client import LLMClient
from app.settings import PROJECT_ROOT


class InterviewCenterService:
    """面试中心用例编排。"""

    def __init__(
        self,
        *,
        repository: ResumeRepository | None = None,
        store: InterviewStoreProtocol | None = None,
        bitable: BitableClientProtocol | None = None,
        llm: QuestionLLMProtocol | None = None,
        output_dir: str | Path | None = None,
        conversation_repository: ConversationRepository | None = None,
    ) -> None:
        self.repository = repository or ResumeRepository.from_settings()
        self.conversation_repository = (
            conversation_repository or ConversationRepository.from_settings()
        )
        self.store = store or GLOBAL_INTERVIEW_STORE
        self.bitable = bitable or MockFeishuBitableClient()
        self.question_generator = InterviewQuestionGenerator(llm or LLMClient())
        self.output_dir = Path(output_dir or PROJECT_ROOT / "data" / "interview_center")
        self.feedback_backfill = FeedbackBackfillService(store=self.store, bitable=self.bitable)

    async def create_session_from_resume(
        self,
        resume_id: str,
        *,
        job_type: str = "",
        conversation: list[dict[str, Any]] | None = None,
        resume_pdf_path: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """从简历创建面试会话并执行主流程。"""

        resume = self._load_resume(resume_id)
        if resume is None:
            raise KeyError("resume_not_found")
        session = self.store.create(
            resume_id=resume.id,
            candidate_name=resume.name or "",
            job_type=job_type or resume.job_type or resume.applied_position or "",
            payload={"resume": resume.model_dump(), "dryRun": dry_run},
        )
        return await self.run_session(
            session,
            resume=resume,
            conversation=conversation or [],
            resume_pdf_path=resume_pdf_path,
        )

    async def create_session_from_payload(
        self,
        resume_payload: dict[str, Any],
        *,
        conversation: list[dict[str, Any]] | None = None,
        resume_pdf_path: str | None = None,
    ) -> dict[str, Any]:
        """从 API 传入 payload 创建面试会话，便于 mock 测试和 dry-run。"""

        resume = Resume(
            id=str(resume_payload.get("id") or resume_payload.get("resumeId") or "dry-run"),
            name=resume_payload.get("name") or resume_payload.get("candidateName"),
            phone=resume_payload.get("phone"),
            applied_position=resume_payload.get("position") or resume_payload.get("job_type"),
            job_type=resume_payload.get("job_type") or resume_payload.get("position"),
            payload=resume_payload,
        )
        session = self.store.create(
            resume_id=resume.id,
            candidate_name=resume.name or "",
            job_type=resume.job_type or resume.applied_position or "",
            payload={"resume": resume.model_dump(), "dryRun": True},
        )
        return await self.run_session(
            session,
            resume=resume,
            conversation=conversation or [],
            resume_pdf_path=resume_pdf_path,
        )

    async def run_session(
        self,
        session: InterviewSession,
        *,
        resume: Resume,
        conversation: list[dict[str, Any]],
        resume_pdf_path: str | None = None,
    ) -> dict[str, Any]:
        """执行面试中心主流程。"""

        candidates = await self._load_bitable_candidates()
        session.matches = match_candidates(_resume_query(resume), candidates)
        session.questions = await self.question_generator.generate(
            resume=resume.model_dump(),
            job_type=session.job_type,
            conversation=conversation,
        )
        if resume_pdf_path:
            session.resume_image_path = str(self._render_resume_png(session.id, resume_pdf_path))
            resume_file_token = await self.bitable.upload_file(session.resume_image_path)
        else:
            resume_file_token = ""
        session.summary_image_path = str(self._render_summary_png(session))
        summary_file_token = await self.bitable.upload_file(session.summary_image_path)
        record = await self._sync_session_to_bitable(
            session,
            resume=resume,
            resume_file_token=resume_file_token,
            summary_file_token=summary_file_token,
        )
        session.bitable_record_id = str(record.get("record_id") or "")
        session.status = "ready"
        self.store.save(session)
        return {"session": session.to_dict(), "bitableRecord": record}

    async def sync_session_to_bitable(self, session_id: str) -> dict[str, Any]:
        """重新同步已有会话到 bitable。"""

        session = self._require_session(session_id)
        record = await self.bitable.create_record(
            BITABLE_TABLES.sessions,
            self._session_fields(session, summary_file_token=""),
        )
        session.bitable_record_id = str(record.get("record_id") or "")
        self.store.save(session)
        return {"session": session.to_dict(), "bitableRecord": record}

    async def backfill_feedback(
        self,
        session_id: str,
        *,
        result: str,
        feedback: str,
        interviewer: str = "",
    ) -> dict[str, Any]:
        """回填面试反馈。"""

        return await self.feedback_backfill.backfill(
            session_id,
            result=result,
            feedback=feedback,
            interviewer=interviewer,
        )

    def list_sessions(self) -> list[dict[str, Any]]:
        """列出会话。"""

        return [session.to_dict() for session in self.store.list()]

    def get_session(self, session_id: str) -> dict[str, Any]:
        """读取会话。"""

        return self._require_session(session_id).to_dict()

    def locate_resume_conversation(self, resume_id: str) -> dict[str, Any]:
        """Locate the platform conversation behind a resume library entry."""

        resume = self._load_resume(resume_id)
        if resume is None:
            raise KeyError("resume_not_found")
        if resume.linked_session_id:
            session = self.conversation_repository.get_session(resume.linked_session_id)
            if session is not None:
                return {
                    "resumeId": resume.id,
                    "matchMode": "linked_session_id",
                    "requiresConfirmation": False,
                    "session": _session_payload(session),
                    "candidates": [],
                }
        name = resume.parsed_name or resume.name or ""
        position = resume.job_type or resume.applied_position or ""
        candidates = self.conversation_repository.search_by_candidate_name(
            candidate_name=name,
            position=position,
        )
        return {
            "resumeId": resume.id,
            "matchMode": "parsed_name_position" if candidates else "none",
            "requiresConfirmation": bool(candidates),
            "session": None,
            "candidates": [_session_payload(session) for session in candidates],
        }

    def oauth(self) -> FeishuOAuthService:
        """返回 OAuth 服务。"""

        return FeishuOAuthService()

    async def _load_bitable_candidates(self) -> list[dict[str, Any]]:
        records = await self.bitable.list_records(BITABLE_TABLES.candidates)
        return [dict(record.get("fields", record)) for record in records]

    def _load_resume(self, resume_id: str) -> Resume | None:
        record = self.repository.get(resume_id)
        return Resume.from_record(record) if record else None

    def _render_resume_png(self, session_id: str, pdf_path: str) -> Path:
        output_path = self.output_dir / f"{session_id}_resume.png"
        render_resume_image(pdf_path, output_path)
        return output_path

    def _render_summary_png(self, session: InterviewSession) -> Path:
        output_path = self.output_dir / f"{session.id}_summary.png"
        render_summary_image(session.to_dict(), output_path)
        return output_path

    async def _sync_session_to_bitable(
        self,
        session: InterviewSession,
        *,
        resume: Resume,
        resume_file_token: str,
        summary_file_token: str,
    ) -> dict[str, Any]:
        candidate_fields = {
            CandidateFields.NAME: session.candidate_name,
            CandidateFields.PHONE: resume.phone or "",
            CandidateFields.POSITION: session.job_type,
            CandidateFields.RESUME_ID: session.resume_id,
            CandidateFields.RESUME_IMAGE: resume_file_token,
        }
        await self.bitable.create_record(BITABLE_TABLES.candidates, candidate_fields)
        return await self.bitable.create_record(
            BITABLE_TABLES.sessions,
            self._session_fields(session, summary_file_token=summary_file_token),
        )

    def _session_fields(
        self,
        session: InterviewSession,
        *,
        summary_file_token: str,
    ) -> dict[str, Any]:
        return {
            SessionFields.SESSION_ID: session.id,
            SessionFields.RESUME_ID: session.resume_id,
            SessionFields.CANDIDATE: session.candidate_name,
            SessionFields.POSITION: session.job_type,
            SessionFields.QUESTIONS: "\n".join(item["question"] for item in session.questions),
            SessionFields.STATUS: session.status,
            SessionFields.SUMMARY_IMAGE: summary_file_token,
        }

    def _require_session(self, session_id: str) -> InterviewSession:
        session = self.store.get(session_id)
        if session is None:
            raise KeyError("interview_session_not_found")
        return session


async def sync_interview_center() -> dict[str, Any]:
    """兼容旧 stub 的同步入口。"""

    service = InterviewCenterService()
    return {"sessions": service.list_sessions()}


def _resume_query(resume: Resume) -> dict[str, Any]:
    return {
        "name": resume.name,
        "phone": resume.phone or resume.phone_key,
        "job_type": resume.job_type or resume.applied_position,
        "source_platform": resume.source_platform,
    }


def _session_payload(session: ConversationSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "platform": session.platform,
        "owner": session.owner,
        "platformConversationId": session.platform_conversation_id,
        "candidateName": session.candidate_name,
        "position": session.position,
        "label": session.label,
        "currentStage": session.current_stage,
        "nextAction": session.next_action,
        "identityConfidence": session.identity_confidence,
    }
