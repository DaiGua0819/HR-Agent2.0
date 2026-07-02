"""面试中心编排服务。

移植旧 `index.js` 的主流程：简历/会话上下文 → 候选人匹配 → LLM 出题 → 飞书多维表同步
→ 出图 → 会话状态更新。所有外部集成走可 mock 接口。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.core.text import clean_text
from app.domain.conversation.models import ConversationSession
from app.domain.conversation.repository import ConversationRepository
from app.domain.resume.models import Resume
from app.domain.resume.normalize import normalize_phone
from app.domain.resume.repository import ResumeRepository
from app.features.interview_center.asset_sync import BitableAssetSync
from app.features.interview_center.backfill import (
    BACKFILL_DELAY_SECONDS,
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
from app.features.interview_center.feishu.routes import resolve_bitable_target
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
    public_backfill_source,
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
        self.now = now or time.time
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
            now=now,
        )
        self._scheduler_tasks: dict[str, asyncio.Task[None]] = {}

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
        source: str = "manual",
        skip_if_running: bool = False,
    ) -> dict[str, Any]:
        """Sync Feishu calendar events into interview-center sessions."""

        result = await self.calendar_sync.sync(
            calendar_id=calendar_id,
            auto_prepare=auto_prepare,
            auto_prepare_limit=auto_prepare_limit,
            source=source,
            skip_if_running=skip_if_running,
        )
        if result.get("skipped"):
            return result
        result = await self._sync_bitable_resume_images(result)
        if auto_prepare:
            result = await self._auto_prepare_synced_sessions(
                result,
                limit=auto_prepare_limit,
            )
        return result

    def calendar_sync_status(self) -> dict[str, Any]:
        """Return calendar sync status for old-compatible endpoints."""

        return self.calendar_sync.status()

    async def _sync_bitable_resume_images(self, result: dict[str, Any]) -> dict[str, Any]:
        bitable_resume_results = []
        for session_payload in list(result.get("sessions") or []):
            session = self.store.get(str(session_payload.get("id") or ""))
            if session is None or not session.resume_id:
                continue
            resume = self._load_resume(session.resume_id)
            if resume is None:
                bitable_resume_results.append(
                    {
                        "sessionId": session.id,
                        "skipped": True,
                        "reason": "resume_not_found",
                    }
                )
                continue
            resume_payload = _public_resume_payload(resume)
            resume_pdf_path = _resume_pdf_path(resume_payload)
            if not resume_pdf_path:
                bitable_resume_results.append(
                    {
                        "sessionId": session.id,
                        "skipped": True,
                        "reason": "missing_resume_pdf_path",
                    }
                )
                continue
            try:
                sync_result = await self.asset_sync.ensure_resume_image(
                    session,
                    resume_payload,
                    resume_pdf_path=resume_pdf_path,
                )
                bitable_resume_results.append({"sessionId": session.id, **sync_result})
                if sync_result.get("ok"):
                    self.store.append_log(
                        session.id,
                        "info",
                        "synced resume image to interview bitable",
                        {
                            "recordId": sync_result.get("recordId"),
                            "fileToken": (
                                sync_result.get("resumeImage", {}).get("fileToken")
                                if isinstance(sync_result.get("resumeImage"), dict)
                                else ""
                            ),
                        },
                    )
            except Exception as exc:
                payload = getattr(exc, "payload", {}) or {}
                bitable_resume_results.append(
                    {
                        "sessionId": session.id,
                        "ok": False,
                        "error": str(exc) or "sync_resume_image_failed",
                        "payload": payload,
                    }
                )
                self.store.append_log(
                    session.id,
                    "warn",
                    str(exc) or "sync_resume_image_failed",
                    payload,
                )
        range_payload = result.get("range") or {}
        next_result = {
            **result,
            "bitableResumeResults": bitable_resume_results,
            "sessions": await self.list_sessions_enriched(
                start_time=int(range_payload.get("startTime") or 0),
                end_time=int(range_payload.get("endTime") or 0),
                protection_source="calendar_sync_result",
            ),
        }
        if self.calendar_sync.last_result is not None:
            self.calendar_sync.last_result = {
                **self.calendar_sync.last_result,
                "bitableResumeSynced": sum(
                    1 for item in bitable_resume_results if item.get("ok")
                ),
                "bitableResumeSkipped": sum(
                    1 for item in bitable_resume_results if item.get("skipped")
                ),
                "bitableResumeErrors": sum(
                    1 for item in bitable_resume_results if item.get("ok") is False
                ),
            }
        return next_result

    async def _auto_prepare_synced_sessions(
        self,
        result: dict[str, Any],
        *,
        limit: int,
    ) -> dict[str, Any]:
        prepared = []
        prepare_errors = []
        max_count = max(0, int(limit or 0))
        for session_payload in list(result.get("sessions") or []):
            if len(prepared) >= max_count:
                break
            if not session_payload.get("resumeId"):
                continue
            if session_payload.get("feishuDoc", {}).get("documentId"):
                continue
            try:
                prepared_result = await self.prepare_session(str(session_payload["id"]))
                prepared.append(prepared_result["session"])
            except Exception as exc:
                error = {
                    "sessionId": str(session_payload.get("id") or ""),
                    "error": str(exc) or "auto_prepare_failed",
                }
                prepare_errors.append(error)
                self.store.append_log(error["sessionId"], "error", error["error"], {})
        range_payload = result.get("range") or {}
        next_result = {
            **result,
            "prepared": len(prepared),
            "prepareErrors": prepare_errors,
            "sessions": await self.list_sessions_enriched(
                start_time=int(range_payload.get("startTime") or 0),
                end_time=int(range_payload.get("endTime") or 0),
                protection_source="calendar_sync_result",
            ),
        }
        if self.calendar_sync.last_result is not None:
            self.calendar_sync.last_result = {
                **self.calendar_sync.last_result,
                "prepared": len(prepared),
                "prepareErrors": len(prepare_errors),
            }
        return next_result

    @property
    def scheduler_running(self) -> bool:
        """Whether any background interview-center scheduler task is active."""

        return any(not task.done() for task in self._scheduler_tasks.values())

    def start_schedulers(
        self,
        *,
        initial_calendar_delay: float | None = None,
        initial_backfill_delay: float | None = None,
    ) -> None:
        """Start old-compatible background scheduler loops."""

        if self.calendar_sync.enabled and "calendar" not in self._scheduler_tasks:
            self._scheduler_tasks["calendar"] = asyncio.create_task(
                self._scheduler_loop(
                    initial_delay=(
                        min(30.0, self.calendar_sync.interval_ms / 1000)
                        if initial_calendar_delay is None
                        else initial_calendar_delay
                    ),
                    interval_seconds=self.calendar_sync.interval_ms / 1000,
                    tick=self.run_auto_calendar_sync_tick,
                )
            )
        if self.backfill_service.enabled and "backfill" not in self._scheduler_tasks:
            self._scheduler_tasks["backfill"] = asyncio.create_task(
                self._scheduler_loop(
                    initial_delay=(
                        self.backfill_service.interval_ms / 1000
                        if initial_backfill_delay is None
                        else initial_backfill_delay
                    ),
                    interval_seconds=self.backfill_service.interval_ms / 1000,
                    tick=self.run_auto_backfill_tick,
                )
            )

    async def stop_schedulers(self) -> None:
        """Cancel background scheduler loops."""

        tasks = list(self._scheduler_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._scheduler_tasks.clear()

    async def _scheduler_loop(
        self,
        *,
        initial_delay: float,
        interval_seconds: float,
        tick: Any,
    ) -> None:
        await asyncio.sleep(max(0.0, initial_delay))
        while True:
            await tick()
            await asyncio.sleep(max(1.0, interval_seconds))

    async def run_auto_calendar_sync_tick(self) -> dict[str, Any]:
        """Run one old-compatible automatic calendar sync tick."""

        if not self.calendar_sync.enabled or self.calendar_sync.running:
            return self.calendar_sync.status()
        if not self.oauth_service.status().get("connected"):
            self.calendar_sync.last_error = "飞书未授权，跳过自动日历同步"
            return self.calendar_sync.status()
        try:
            await self.sync_calendar(
                calendar_id="primary",
                auto_prepare=False,
                auto_prepare_limit=0,
                source="auto",
                skip_if_running=True,
            )
        except Exception as exc:
            self.calendar_sync.last_error = str(exc) or "自动同步飞书日历失败"
            self.store.append_log("", "warn", self.calendar_sync.last_error, {})
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
        early_override_reason: str = "",
        early_override_token: str = "",
    ) -> dict[str, Any]:
        """Backfill interview evaluation from meeting/minutes sources."""

        return await self.backfill_service.backfill(
            session_id,
            force=force,
            early_override=early_override,
            early_override_reason=early_override_reason,
            early_override_token=early_override_token,
        )

    def backfill_status(self) -> dict[str, Any]:
        """Return backfill scheduler/service status."""

        return self.backfill_service.status()

    async def run_auto_backfill_tick(
        self,
        *,
        max_per_tick: int | None = None,
        max_attempts: int | None = None,
    ) -> dict[str, Any]:
        """Run one old-compatible automatic interview backfill tick."""

        return await self.backfill_service.run_auto_tick(
            max_per_tick=max_per_tick,
            max_attempts=max_attempts,
        )

    def backfill_source(self, session_id: str) -> dict[str, Any]:
        """Return the stored public backfill source for a session."""

        session = self._require_session(session_id)
        evaluation_source = (
            session.interview_evaluation.get("source")
            if isinstance(session.interview_evaluation, dict)
            else {}
        )
        source = session.backfill_source or evaluation_source or {}
        return {
            "sessionId": session.id,
            "source": public_backfill_source(source),
            "lastBackfillError": session.last_backfill_error,
        }

    async def bind_session(
        self,
        session_id: str,
        *,
        resume_id: str,
        prepare: bool = False,
    ) -> dict[str, Any]:
        """Manually bind a resume to a calendar session, matching the old UI flow."""

        resume = self._load_resume(resume_id)
        if resume is None:
            raise KeyError("resume_not_found")
        session = self._require_session(session_id)
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
        protection_source: str = "sessions_response",
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
            session = self._protect_premature_backfill(
                session,
                source=protection_source,
            )
            sessions.append(session.to_dict())
        return sessions

    async def list_sessions_enriched(
        self,
        *,
        start_time: int = 0,
        end_time: int = 0,
        status: str = "",
        protection_source: str = "sessions_response",
    ) -> list[dict[str, Any]]:
        """List sessions with old Bitable-backed interviewFlow metadata."""

        sessions = self.list_sessions(
            start_time=start_time,
            end_time=end_time,
            status=status,
            protection_source=protection_source,
        )
        return await self._enrich_sessions_with_bitable_flow(sessions)

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

    async def _enrich_sessions_with_bitable_flow(
        self,
        sessions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not sessions:
            return []
        table_ids = sorted(
            {
                table_id
                for session in sessions
                if (table_id := _session_bitable_table_id(session))
            }
        )
        if not table_ids:
            return sessions
        records_by_table: dict[str, list[dict[str, Any]]] = {}
        bitable_error = ""
        for table_id in table_ids:
            try:
                records_by_table[table_id] = await self.bitable.list_records(table_id)
            except Exception as exc:
                bitable_error = str(exc) or "read_bitable_interview_flow_failed"
                records_by_table[table_id] = []
        enriched = []
        for session in sessions:
            table_id = _session_bitable_table_id(session)
            record = _find_bitable_record_for_session(
                session,
                records_by_table.get(table_id, []),
            )
            if record or bitable_error:
                session = {
                    **session,
                    "interviewFlow": _make_bitable_interview_flow(
                        session,
                        record,
                        bitable_error=bitable_error if not record else "",
                    ),
                }
            enriched.append(session)
        return enriched

    def _require_session(self, session_id: str) -> InterviewSession:
        session = self.store.get(session_id)
        if session is None:
            raise KeyError("interview_session_not_found")
        return session

    def _protect_premature_backfill(
        self,
        session: InterviewSession,
        *,
        source: str,
    ) -> InterviewSession:
        guard = self._premature_backfill_guard(session)
        if not guard:
            return session
        return self._clear_premature_backfill(session, guard, source=source)

    def _premature_backfill_guard(
        self,
        session: InterviewSession,
    ) -> dict[str, Any] | None:
        if not session.interview_evaluation:
            return None
        available_at = _backfill_available_at(session)
        override = (
            session.payload.get("earlyBackfillOverride")
            if isinstance(session.payload.get("earlyBackfillOverride"), dict)
            else {}
        )
        if override.get("usedAt") and _safe_int(override.get("availableAt")) == available_at:
            return None
        now_seconds = int(self.now())
        if available_at and now_seconds < available_at:
            return {
                "reason": "interview_not_finished",
                "availableAt": available_at,
                "nowSeconds": now_seconds,
                "endTime": int(session.end_time or 0),
            }
        return None

    def _clear_premature_backfill(
        self,
        session: InterviewSession,
        guard: dict[str, Any],
        *,
        source: str,
    ) -> InterviewSession:
        stale_payload = {
            "evaluation": dict(session.interview_evaluation),
            "backfillSource": (
                dict(session.backfill_source)
                if session.backfill_source
                else session.interview_evaluation.get("source")
            ),
            "ruleSuggestionIds": list(session.rule_suggestion_ids),
            "backfilledAt": str(session.payload.get("backfilledAt") or ""),
            "clearedAt": now_iso(),
            "reason": guard["reason"],
            "source": source,
            "availableAt": guard["availableAt"],
            "endTime": guard["endTime"],
        }
        try:
            self._clear_resume_premature_backfill(session, stale_payload)
        except Exception as exc:
            self.store.append_log(
                session.id,
                "warn",
                str(exc) or "clear_resume_premature_backfill_failed",
                getattr(exc, "payload", {}) or {},
            )
        history = [
            stale_payload,
            *list(session.payload.get("staleInterviewEvaluationHistory") or []),
        ][:5]
        session.status = _status_without_backfill(session)
        session.interview_evaluation = {}
        session.backfill_source = {}
        session.rule_suggestion_ids = []
        session.last_backfill_error = ""
        session.payload = {
            **session.payload,
            "backfillStartedAt": "",
            "backfilledAt": "",
            "staleInterviewEvaluation": stale_payload,
            "staleInterviewEvaluationHistory": history,
        }
        saved = self.store.save(session)
        self.store.append_log(
            session.id,
            "warn",
            "cleared premature interview backfill result",
            stale_payload,
        )
        return saved

    def _clear_resume_premature_backfill(
        self,
        session: InterviewSession,
        stale_payload: dict[str, Any],
    ) -> bool:
        if not session.resume_id:
            return False
        record = self.repository.get(session.resume_id)
        if record is None:
            return False
        evaluation = record.payload.get("interviewEvaluation")
        if not evaluation:
            return False
        if (
            isinstance(evaluation, dict)
            and evaluation.get("sessionId")
            and evaluation.get("sessionId") != session.id
        ):
            return False
        payload = dict(record.payload)
        payload["staleInterviewEvaluation"] = {
            **stale_payload,
            "evaluation": evaluation,
        }
        payload["updatedAt"] = now_iso()
        payload.pop("interviewEvaluation", None)
        self.repository.save(Resume.from_record(replace(record, payload=payload)))
        return True


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


def _resume_pdf_path(resume: dict[str, Any]) -> str:
    nested_payload = resume.get("payload") if isinstance(resume.get("payload"), dict) else {}
    for source in (resume, nested_payload):
        for key in (
            "resumePdfPath",
            "resume_pdf_path",
            "pdfPath",
            "pdf_path",
            "filePath",
            "file_path",
            "downloadPath",
            "download_path",
        ):
            value = source.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def _session_bitable_table_id(session: dict[str, Any]) -> str:
    table_id = str(
        session.get("bitableTableId")
        or session.get("bitable_table_id")
        or _dict_value(session.get("bitable")).get("tableId")
        or ""
    )
    if table_id:
        return table_id
    target = resolve_bitable_target(
        {
            "session": session,
            "resume": session.get("resume") or session.get("matchedResume") or {},
        }
    )
    return target.table_id


def _find_bitable_record_for_session(
    session: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    direct_id = _session_bitable_record_id(session)
    if direct_id:
        matched = next(
            (record for record in records if _bitable_record_id(record) == direct_id),
            None,
        )
        if matched:
            return matched
    phone = normalize_phone(
        _dict_value(session.get("resume")).get("phone")
        or session.get("phone")
        or session.get("candidatePhone")
    )
    if phone:
        matched = next(
            (
                record
                for record in records
                if _bitable_field_contains_phone(
                    record.get("fields", {}).get("候选人联系电话"),
                    phone,
                )
            ),
            None,
        )
        if matched:
            return matched
    names = {
        _normalize_bitable_match_text(value)
        for value in (
            _dict_value(session.get("resume")).get("name"),
            _dict_value(session.get("matchedResume")).get("name"),
            session.get("candidateName"),
            _dict_value(session.get("bitable")).get("fields", {}).get("姓名")
            if isinstance(_dict_value(session.get("bitable")).get("fields"), dict)
            else "",
            _dict_value(session.get("bitable")).get("fields", {}).get("候选人姓名")
            if isinstance(_dict_value(session.get("bitable")).get("fields"), dict)
            else "",
        )
        if _normalize_bitable_match_text(value)
    }
    if not names:
        return None
    return next(
        (
            record
            for record in records
            if any(
                _normalize_bitable_match_text(_extract_bitable_field_text(value)) in names
                for value in (
                    record.get("fields", {}).get("姓名"),
                    record.get("fields", {}).get("候选人姓名"),
                )
            )
        ),
        None,
    )


def _make_bitable_interview_flow(
    session: dict[str, Any],
    record: dict[str, Any] | None,
    *,
    bitable_error: str = "",
) -> dict[str, Any]:
    fallback = dict(session.get("interviewFlow") or {})
    if not record:
        return {**fallback, "error": bitable_error or fallback.get("error", "")}
    fields = record.get("fields") or {}
    stage_text = _extract_bitable_field_text(
        fields.get("面试阶段") or fields.get("interviewStage")
    )
    group = _derive_bitable_interview_group(
        stage_text=stage_text,
        fields=fields,
        session=session,
    )
    round_payload = _derive_bitable_interview_round(stage_text=stage_text, session=session)
    return {
        "groupKey": group["key"],
        "groupLabel": group["label"],
        "roundKey": round_payload["key"],
        "roundLabel": round_payload["label"],
        "stageText": stage_text,
        "source": "bitable",
        "recordId": _bitable_record_id(record) or _session_bitable_record_id(session),
        "error": bitable_error,
    }


def _derive_bitable_interview_group(
    *,
    stage_text: str,
    fields: dict[str, Any],
    session: dict[str, Any],
) -> dict[str, str]:
    compact_stage = clean_text(stage_text)
    if compact_stage:
        if any(
            keyword in compact_stage
            for keyword in (
                "简历通过",
                "待面试",
                "待初面",
                "待一面",
                "待二面",
                "待复试",
                "已约",
                "约面",
                "邀约",
            )
        ):
            return {"key": "waiting", "label": "等待面试"}
        if any(
            keyword in compact_stage
            for keyword in (
                "初面",
                "初试",
                "一面",
                "二面",
                "二试",
                "复试",
                "复面",
                "终面",
                "面试",
                "通过",
                "未通过",
                "淘汰",
                "不合适",
                "完成",
                "结束",
            )
        ):
            return {"key": "completed", "label": "已经面试"}
    if (
        session.get("interviewEvaluation")
        or _dict_value(session.get("bitableInterviewRecordImage")).get("fileToken")
        or _extract_bitable_field_text(fields.get("面试记录"))
        or _extract_bitable_field_text(fields.get("HR面试评价"))
        or _extract_bitable_field_text(fields.get("复试结果评价"))
    ):
        return {"key": "completed", "label": "已经面试"}
    end_time = _safe_int(session.get("endTime") or session.get("startTime"))
    return (
        {"key": "completed", "label": "已经面试"}
        if end_time and end_time < int(time.time())
        else {"key": "waiting", "label": "等待面试"}
    )


def _derive_bitable_interview_round(
    *,
    stage_text: str,
    session: dict[str, Any],
) -> dict[str, str]:
    text = clean_text(
        " ".join(
            str(value or "")
            for value in (
                stage_text,
                session.get("title"),
                session.get("description"),
            )
        )
    ).lower()
    if any(
        keyword in text
        for keyword in ("二面", "二试", "复试", "复面", "second", "2面", "2试")
    ):
        return {"key": "second", "label": "二面"}
    if any(keyword in text for keyword in ("终面", "三面", "三试")):
        return {"key": "other", "label": "其他轮次"}
    if any(
        keyword in text
        for keyword in ("初面", "初试", "一面", "一试", "简历通过", "待面试", "面试")
    ) or not text:
        return {"key": "first", "label": "初面"}
    return {"key": "other", "label": "其他轮次"}


def _session_bitable_record_id(session: dict[str, Any]) -> str:
    return str(
        session.get("bitableRecordId")
        or _dict_value(session.get("bitable")).get("recordId")
        or _dict_value(session.get("bitableResumeImage")).get("recordId")
        or _dict_value(session.get("bitableInterviewRecordImage")).get("recordId")
        or _dict_value(session.get("bitableSkillEvaluationDocument")).get("recordId")
        or ""
    )


def _bitable_record_id(record: dict[str, Any]) -> str:
    return str(record.get("record_id") or record.get("id") or "")


def _bitable_field_contains_phone(value: Any, phone: str) -> bool:
    field_text = _extract_bitable_field_text(value)
    normalized = normalize_phone(field_text)
    if normalized == phone:
        return True
    digits = "".join(ch for ch in clean_text(field_text) if ch.isdigit())
    return bool(digits and phone in digits)


def _extract_bitable_field_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str | int | float | bool):
        return clean_text(value)
    if isinstance(value, list | tuple | set):
        return clean_text(" ".join(_extract_bitable_field_text(item) for item in value))
    if isinstance(value, dict):
        parts = [
            value.get("text"),
            value.get("name"),
            value.get("value"),
            value.get("email"),
            value.get("id"),
            _extract_bitable_field_text(value.get("text_arr")),
        ]
        return clean_text(" ".join(str(part) for part in parts if part not in (None, "")))
    return clean_text(value)


def _normalize_bitable_match_text(value: Any) -> str:
    return clean_text(value).lower()


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _backfill_available_at(session: InterviewSession) -> int:
    base_time = int(session.end_time or session.start_time or 0)
    return base_time + BACKFILL_DELAY_SECONDS if base_time else 0


def _status_without_backfill(session: InterviewSession) -> str:
    if session.feishu_doc.get("documentId"):
        if session.feishu_doc.get("contentSynced") is False:
            return "prepared_local"
        return "prepared"
    if session.question_set:
        return "questions_generated"
    if session.resume_id:
        return "matched"
    if session.status in {"backfilling", "backfill_failed", "needs_review", "completed"}:
        return "synced"
    return session.status or "synced"


def _normalize_review_decision(value: str) -> str:
    decision = str(value or "").strip()
    if decision in {"passed", "rejected", "need_followup"}:
        return decision
    return "passed"


def _review_status_for_decision(decision: str) -> str:
    return "needs_review" if decision == "need_followup" else "completed"


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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
