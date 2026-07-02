"""Interview evaluation backfill orchestration."""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from typing import Any, Protocol

from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository
from app.features.interview_center.asset_sync import BitableAssetSync
from app.features.interview_center.feishu.meeting import (
    EmptyMeetingSourceClient,
    MeetingSourceClientProtocol,
)
from app.features.interview_center.store import InterviewSession, InterviewStoreProtocol, now_iso

BACKFILL_DELAY_SECONDS = 10 * 60


class EvaluationGeneratorProtocol(Protocol):
    """Generate structured evaluation from interview transcript text."""

    async def generate(
        self,
        *,
        resume: dict[str, Any],
        session: InterviewSession,
        interview_text: str,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        """Return an interview evaluation payload."""


class DefaultEvaluationGenerator:
    """Conservative local fallback for tests and dry-run-safe operation."""

    async def generate(
        self,
        *,
        resume: dict[str, Any],
        session: InterviewSession,
        interview_text: str,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        _ = resume, session, source
        return {
            "summary": interview_text[:300],
            "overallRecommendation": "needs_review",
            "risks": [],
            "suggestedRuleChanges": [],
        }


class BackfillService:
    """Backfill interview evaluation from meeting/minutes sources."""

    def __init__(
        self,
        *,
        store: InterviewStoreProtocol,
        repository: ResumeRepository,
        meeting_client: MeetingSourceClientProtocol | None = None,
        evaluation_generator: EvaluationGeneratorProtocol | None = None,
        asset_sync: BitableAssetSync | Any | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.store = store
        self.repository = repository
        self.meeting_client = meeting_client or EmptyMeetingSourceClient()
        self.evaluation_generator = evaluation_generator or DefaultEvaluationGenerator()
        self.asset_sync = asset_sync
        self.now = now or time.time
        self.running: set[str] = set()
        self.last_result: dict[str, Any] | None = None
        self.last_error = ""

    async def backfill(
        self,
        session_id: str,
        *,
        force: bool = False,
        early_override: bool = False,
        early_override_token: str = "",
    ) -> dict[str, Any]:
        """Backfill one interview session and return an API-compatible payload."""

        _ = force
        session = self._require_session(session_id)
        if not session.resume_id:
            raise ValueError("interview_session_resume_required")
        self._enforce_ten_minute_guard(
            session,
            early_override=early_override,
            early_override_token=early_override_token,
        )
        resume_record = self.repository.get(session.resume_id)
        if resume_record is None:
            raise KeyError("bound_resume_not_found")
        if session.id in self.running:
            return {"session": session.to_dict()}
        self.running.add(session.id)
        try:
            session.status = "backfilling"
            session.backfill_attempts += 1
            session.last_backfill_error = ""
            self.store.save(session)
            collected = await self.meeting_client.collect_sources(session)
            source = dict(collected.get("source") or {})
            text = str(collected.get("text") or "").strip()
            if not text:
                failed = self._save_failed(session, source, "no_valid_interview_record")
                return {"session": failed.to_dict()}
            resume = Resume.from_record(resume_record)
            evaluation = await self._generate_evaluation(
                resume=resume.model_dump(),
                session=session,
                interview_text=text,
                source=source,
            )
            interview_evaluation = {
                **evaluation,
                "sessionId": session.id,
                "feishuEventId": session.feishu_event_id,
                "feishuDocUrl": session.feishu_doc.get("url") or "",
                "source": source,
                "sourceErrors": source.get("errors") or [],
                "updatedAt": now_iso(),
                "humanReviewRequired": True,
            }
            self.repository.update(
                session.resume_id,
                {"interviewEvaluation": interview_evaluation},
            )
            session.interview_evaluation = interview_evaluation
            session.backfill_source = source
            session.status = "needs_review"
            session.last_backfill_error = ""
            session.payload = {**session.payload, "backfilledAt": now_iso()}
            saved = self.store.save(session)
            await self._sync_assets(saved, resume.model_dump(), interview_evaluation)
            saved = self.store.get(session.id) or saved
            self.store.append_log(
                session.id,
                "info",
                "interview backfill completed",
                {"source": source},
            )
            self.last_result = {
                "sessionId": session.id,
                "status": saved.status,
                "source": source.get("source") or "",
                "backfilledAt": now_iso(),
            }
            return {"session": saved.to_dict()}
        except Exception as exc:
            self.last_error = str(exc)
            if not isinstance(exc, ValueError | KeyError):
                self._save_failed(session, session.backfill_source, str(exc))
            raise
        finally:
            self.running.discard(session.id)

    def status(self) -> dict[str, Any]:
        """Return old-compatible backfill status."""

        return {
            "running": bool(self.running),
            "runningSessionIds": sorted(self.running),
            "lastError": self.last_error,
            "lastResult": self.last_result,
        }

    def _require_session(self, session_id: str) -> InterviewSession:
        session = self.store.get(session_id)
        if session is None:
            raise KeyError("interview_session_not_found")
        return session

    def _enforce_ten_minute_guard(
        self,
        session: InterviewSession,
        *,
        early_override: bool,
        early_override_token: str,
    ) -> None:
        if not session.end_time:
            return
        available_at = session.end_time + BACKFILL_DELAY_SECONDS
        if int(self.now()) >= available_at:
            return
        if early_override and early_override_token == session.id:
            return
        raise ValueError("backfill_not_available")

    def _save_failed(
        self,
        session: InterviewSession,
        source: dict[str, Any],
        error: str,
    ) -> InterviewSession:
        session.status = "backfill_failed"
        session.backfill_source = source
        session.last_backfill_error = error
        session.payload = {**session.payload, "backfilledAt": now_iso()}
        saved = self.store.save(session)
        self.store.append_log(session.id, "warn", "interview backfill failed", source)
        self.last_result = {"sessionId": session.id, "status": saved.status, "source": source}
        return saved

    async def _generate_evaluation(
        self,
        *,
        resume: dict[str, Any],
        session: InterviewSession,
        interview_text: str,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        result = self.evaluation_generator.generate(
            resume=resume,
            session=session,
            interview_text=interview_text,
            source=source,
        )
        if inspect.isawaitable(result):
            return dict(await result)
        return dict(result)

    async def _sync_assets(
        self,
        session: InterviewSession,
        resume: dict[str, Any],
        evaluation: dict[str, Any],
    ) -> None:
        if self.asset_sync is None:
            return
        await self.asset_sync.ensure_interview_record_image(session, resume)
        document = {
            "documentId": f"evaluation:{session.id}",
            "title": evaluation.get("summary") or "技能评价",
            "url": session.feishu_doc.get("url") or "",
        }
        second_round = str(evaluation.get("round") or "").lower() == "second"
        await self.asset_sync.ensure_evaluation_document(
            session,
            resume,
            document,
            second_round=second_round,
        )
