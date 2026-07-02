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
from app.features.interview_center.asset_sync import BitableAssetSync
from app.features.interview_center.backfill import (
    BackfillService,
    EvaluationGeneratorProtocol,
)
from app.features.interview_center.calendar_sync import (
    CalendarClientProtocol,
    CalendarSyncService,
    FeishuCalendarClient,
)
from app.features.interview_center.candidate_matcher import match_candidates
from app.features.interview_center.feedback_backfill import FeedbackBackfillService
from app.features.interview_center.feishu.assets import (
    BITABLE_TABLES,
    CandidateFields,
    SessionFields,
)
from app.features.interview_center.feishu.bitable import (
    BitableClientProtocol,
    FeishuBitableClient,
    MockFeishuBitableClient,
)
from app.features.interview_center.feishu.client import FeishuStoredUserTokenProvider
from app.features.interview_center.feishu.docx import (
    FeishuInterviewDocClient,
    InterviewDocClientProtocol,
    build_interview_document_text,
)
from app.features.interview_center.feishu.meeting import (
    FeishuMeetingSourceClient,
    MeetingSourceClientProtocol,
)
from app.features.interview_center.feishu.oauth import (
    FeishuOAuthHttpClientProtocol,
    FeishuOAuthService,
)
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
    now_iso,
)
from app.llm.client import LLMClient
from app.settings import PROJECT_ROOT, load_settings


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
        calendar_client: CalendarClientProtocol | None = None,
        doc_client: InterviewDocClientProtocol | None = None,
        meeting_client: MeetingSourceClientProtocol | None = None,
        oauth_client: FeishuOAuthHttpClientProtocol | None = None,
        evaluation_generator: EvaluationGeneratorProtocol | None = None,
        asset_sync: BitableAssetSync | Any | None = None,
        now: Any | None = None,
    ) -> None:
        self.repository = repository or ResumeRepository.from_settings()
        self.conversation_repository = (
            conversation_repository or ConversationRepository.from_settings()
        )
        self.store = store or GLOBAL_INTERVIEW_STORE
        self.bitable = bitable or _default_bitable_client()
        self.user_token_provider = FeishuStoredUserTokenProvider(store=self.store)
        self.doc_client = doc_client or FeishuInterviewDocClient(
            token_provider=self.user_token_provider
        )
        self.oauth_service = FeishuOAuthService(store=self.store, http_client=oauth_client)
        self.question_generator = InterviewQuestionGenerator(llm or LLMClient())
        self.output_dir = Path(output_dir or PROJECT_ROOT / "data" / "interview_center")
        self.asset_sync = asset_sync or BitableAssetSync(
            store=self.store,
            bitable=self.bitable,
            output_dir=self.output_dir,
        )
        self.feedback_backfill = FeedbackBackfillService(store=self.store, bitable=self.bitable)
        self.backfill_service = BackfillService(
            store=self.store,
            repository=self.repository,
            meeting_client=meeting_client
            or FeishuMeetingSourceClient(token_provider=self.user_token_provider),
            evaluation_generator=evaluation_generator,
            asset_sync=self.asset_sync,
            now=now,
        )
        self.calendar_sync = CalendarSyncService(
            store=self.store,
            repository=self.repository,
            calendar_client=calendar_client
            or FeishuCalendarClient(token_provider=self.user_token_provider),
        )

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

    async def sync_calendar(
        self,
        *,
        calendar_id: str = "primary",
        auto_prepare: bool = False,
        auto_prepare_limit: int = 12,
    ) -> dict[str, Any]:
        """Sync Feishu calendar events into interview-center sessions."""

        return await self.calendar_sync.sync(
            calendar_id=calendar_id,
            auto_prepare=auto_prepare,
            auto_prepare_limit=auto_prepare_limit,
            source="manual",
        )

    def calendar_sync_status(self) -> dict[str, Any]:
        """Return calendar sync status for old-compatible endpoints."""

        return self.calendar_sync.status()

    async def prepare_session(self, session_id: str, *, force: bool = False) -> dict[str, Any]:
        """Generate interview questions and create the Feishu Docx question package."""

        session = self._require_session(session_id)
        if not session.resume_id:
            raise ValueError("interview_session_resume_required")
        resume = self._load_resume(session.resume_id)
        if resume is None:
            raise KeyError("bound_resume_not_found")
        resume_payload = resume.model_dump()
        question_set = session.question_set if not force else {}
        questions = list(question_set.get("questions") or [])
        if not questions:
            questions = await self.question_generator.generate(
                resume=resume_payload,
                job_type=session.job_type or resume.job_type or resume.applied_position or "",
                conversation=[],
            )
            question_set = {
                "questions": questions,
                "jobType": session.job_type or resume.job_type or resume.applied_position or "",
                "generatedAt": now_iso(),
            }
        session.questions = questions
        session.question_set = dict(question_set)
        session.payload = {
            **session.payload,
            "resume": resume_payload,
            "preparedAt": now_iso(),
        }

        feishu_doc = dict(session.feishu_doc if not force else {})
        doc_error = ""
        if force or not feishu_doc.get("documentId"):
            title = _document_title(session, resume_payload)
            text = build_interview_document_text(
                candidate_name=session.candidate_name or resume.name or "",
                job_type=session.job_type or resume.job_type or resume.applied_position or "",
                resume=resume_payload,
                question_set=session.question_set,
            )
            try:
                feishu_doc = {
                    **await self.doc_client.create_document_from_text(title, text),
                    "createdAt": now_iso(),
                }
                self.store.append_log(
                    session.id,
                    "info",
                    "created interview question document",
                    {
                        "documentId": feishu_doc.get("documentId"),
                        "url": feishu_doc.get("url"),
                    },
                )
            except Exception as exc:
                doc_error = str(exc) or "create_interview_doc_failed"
                feishu_doc = {
                    "contentSynced": False,
                    "contentError": doc_error,
                    "updatedAt": now_iso(),
                }
                self.store.append_log(session.id, "error", doc_error, {})
        session.feishu_doc = feishu_doc
        document_ready = bool(
            feishu_doc.get("documentId") and feishu_doc.get("contentSynced") is not False
        )
        session.status = "prepared" if document_ready else "prepared_local"
        if doc_error:
            session.payload = {**session.payload, "prepareErrors": [doc_error]}
        else:
            session.payload = {**session.payload, "prepareErrors": []}
        self.store.save(session)
        return {"session": session.to_dict(), "feishuDoc": feishu_doc}

    async def backfill_session(
        self,
        session_id: str,
        *,
        force: bool = False,
        early_override: bool = False,
        early_override_token: str = "",
    ) -> dict[str, Any]:
        """Backfill interview evaluation from meeting/minutes sources."""

        return await self.backfill_service.backfill(
            session_id,
            force=force,
            early_override=early_override,
            early_override_token=early_override_token,
        )

    def backfill_status(self) -> dict[str, Any]:
        """Return backfill scheduler/service status."""

        return self.backfill_service.status()

    def backfill_source(self, session_id: str) -> dict[str, Any]:
        """Return the stored public backfill source for a session."""

        session = self._require_session(session_id)
        return {"sessionId": session.id, "source": session.backfill_source}

    async def bind_session(
        self,
        session_id: str,
        *,
        resume_id: str,
        prepare: bool = False,
    ) -> dict[str, Any]:
        """Manually bind a resume to a calendar session, matching the old UI flow."""

        session = self._require_session(session_id)
        resume = self._load_resume(resume_id)
        if resume is None:
            raise KeyError("resume_not_found")
        resume_payload = _public_resume_payload(resume)
        matched_resume = {
            "id": resume.id,
            "name": resume_payload.get("name") or "",
            "jobType": resume_payload.get("jobType") or "",
        }
        session.resume_id = resume.id
        session.candidate_name = session.candidate_name or str(
            resume_payload.get("name") or ""
        )
        session.job_type = session.job_type or str(resume_payload.get("jobType") or "")
        session.status = "prepared" if session.question_set else "matched"
        session.payload = {
            **session.payload,
            "resume": resume_payload,
            "matchedResume": matched_resume,
            "matchMode": "manual",
            "manualBoundAt": now_iso(),
        }
        saved = self.store.save(session)
        self.store.append_log(
            saved.id,
            "info",
            "已人工绑定候选人",
            {"resumeId": resume.id, "name": matched_resume["name"]},
        )
        if prepare:
            return await self.prepare_session(saved.id)
        return {"session": saved.to_dict()}

    async def review_session(
        self,
        session_id: str,
        *,
        decision: str = "passed",
        note: str = "",
    ) -> dict[str, Any]:
        """Persist the old interview-center human review/confirm action."""

        session = self._require_session(session_id)
        normalized_decision = _normalize_review_decision(decision)
        reviewed_at = now_iso()
        review = {
            "status": normalized_decision,
            "decision": normalized_decision,
            "note": str(note or "")[:1000],
            "reviewedAt": reviewed_at,
        }
        interview_evaluation = {
            **session.interview_evaluation,
            "review": review,
            "humanReviewRequired": normalized_decision == "need_followup",
            "reviewedAt": reviewed_at,
        }
        human_review = {
            "confirmed": True,
            "decision": normalized_decision,
            "note": review["note"],
            "confirmedAt": reviewed_at,
        }
        session.interview_evaluation = interview_evaluation
        session.status = _review_status_for_decision(normalized_decision)
        session.payload = {**session.payload, "humanReview": human_review}
        saved = self.store.save(session)
        if saved.resume_id:
            self.repository.update(
                saved.resume_id,
                {"interviewEvaluation": interview_evaluation},
            )
        self.store.append_log(
            saved.id,
            "info",
            "interview review completed",
            human_review,
        )
        return {"session": saved.to_dict()}

    def list_sessions(
        self,
        *,
        start_time: int = 0,
        end_time: int = 0,
        status: str = "",
    ) -> list[dict[str, Any]]:
        """列出会话。"""

        sessions = []
        for session in self.store.list():
            if start_time and session.start_time and session.start_time < start_time:
                continue
            if end_time and session.start_time and session.start_time > end_time:
                continue
            if status and session.status != status:
                continue
            if session.payload.get("isInterviewLike") is False:
                continue
            sessions.append(session.to_dict())
        return sessions

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

        return self.oauth_service

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


def _document_title(session: InterviewSession, resume: dict[str, Any]) -> str:
    candidate_name = session.candidate_name or str(resume.get("name") or "候选人")
    job_type = session.job_type or str(
        resume.get("job_type") or resume.get("applied_position") or "面试"
    )
    return f"{candidate_name}-{job_type}-面试问题"


def _public_resume_payload(resume: Resume) -> dict[str, Any]:
    payload = resume.model_dump(mode="json")
    name = resume.name or resume.parsed_name or ""
    job_type = resume.job_type or resume.applied_position or ""
    if name:
        payload["name"] = name
    if job_type:
        payload["jobType"] = job_type
        payload["job_type"] = job_type
    if resume.phone or resume.phone_key:
        payload["phone"] = resume.phone or resume.phone_key
    return payload


def _normalize_review_decision(value: str) -> str:
    decision = str(value or "").strip()
    if decision in {"passed", "rejected", "need_followup"}:
        return decision
    return "passed"


def _review_status_for_decision(decision: str) -> str:
    return "needs_review" if decision == "need_followup" else "completed"


def _default_bitable_client() -> BitableClientProtocol:
    feishu = load_settings().feishu
    if feishu.app_id and feishu.app_secret and feishu.bitable_app_token:
        return FeishuBitableClient(config=feishu)
    return MockFeishuBitableClient()


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
