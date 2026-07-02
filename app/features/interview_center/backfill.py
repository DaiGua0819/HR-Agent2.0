"""Interview evaluation backfill orchestration."""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from datetime import UTC, datetime
from os import getenv
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
DAY_SECONDS = 24 * 60 * 60
AUTO_BACKFILL_INTERVAL_MS = max(
    60_000,
    int(getenv("INTERVIEW_BACKFILL_INTERVAL_MS") or 5 * 60 * 1000),
)
AUTO_BACKFILL_MAX_PER_TICK = max(
    1,
    min(int(getenv("INTERVIEW_BACKFILL_MAX_PER_TICK") or 3), 10),
)
AUTO_BACKFILL_MAX_ATTEMPTS = max(
    1,
    min(int(getenv("INTERVIEW_BACKFILL_MAX_ATTEMPTS") or 3), 10),
)


class BackfillError(ValueError):
    """Backfill domain error with old API response metadata."""

    def __init__(
        self,
        code: str,
        *,
        status_code: int = 409,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.payload = payload or {}


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
        enabled: bool | None = None,
        interval_ms: int | None = None,
        max_per_tick: int | None = None,
        max_attempts: int | None = None,
    ) -> None:
        self.store = store
        self.repository = repository
        self.meeting_client = meeting_client or EmptyMeetingSourceClient()
        self.evaluation_generator = evaluation_generator or DefaultEvaluationGenerator()
        self.asset_sync = asset_sync
        self.now = now or time.time
        self.enabled = (
            _env_enabled("INTERVIEW_AUTO_BACKFILL_ENABLED") if enabled is None else enabled
        )
        self.interval_ms = interval_ms or AUTO_BACKFILL_INTERVAL_MS
        self.max_per_tick = max_per_tick or AUTO_BACKFILL_MAX_PER_TICK
        self.max_attempts = max_attempts or AUTO_BACKFILL_MAX_ATTEMPTS
        self.running: set[str] = set()
        self.auto_running = False
        self.last_run_at = ""
        self.last_processed: list[dict[str, Any]] = []
        self.last_result: dict[str, Any] | None = None
        self.last_error = ""

    async def backfill(
        self,
        session_id: str,
        *,
        force: bool = False,
        early_override: bool = False,
        early_override_reason: str = "",
        early_override_token: str = "",
    ) -> dict[str, Any]:
        """Backfill one interview session and return an API-compatible payload."""

        session = self._require_session(session_id)
        if not session.resume_id:
            raise ValueError("interview_session_resume_required")
        allow_early_backfill = self._enforce_ten_minute_guard(
            session,
            force=force,
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
            if allow_early_backfill:
                session.payload = {
                    **session.payload,
                    "earlyBackfillOverride": _used_early_override_payload(
                        session,
                        available_at=_backfill_available_at(session),
                        reason=early_override_reason,
                    ),
                }
            saved = self.store.save(session)
            try:
                await self._sync_assets(saved, resume.model_dump(), interview_evaluation)
            except Exception as exc:
                self.store.append_log(
                    session.id,
                    "warn",
                    str(exc) or "sync_interview_assets_failed",
                    {},
                )
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

    async def run_auto_tick(
        self,
        *,
        max_per_tick: int | None = None,
        max_attempts: int | None = None,
    ) -> dict[str, Any]:
        """Run one old-compatible automatic backfill scheduler tick."""

        resolved_max_per_tick = _bounded_int(max_per_tick, self.max_per_tick, 1, 10)
        resolved_max_attempts = _bounded_int(max_attempts, self.max_attempts, 1, 10)
        if not self.enabled or self.auto_running:
            return self.status(
                max_per_tick=resolved_max_per_tick,
                max_attempts=resolved_max_attempts,
            )
        self.auto_running = True
        self.last_run_at = now_iso()
        self.last_error = ""
        processed: list[dict[str, Any]] = []
        try:
            candidates = self.auto_candidates(max_attempts=resolved_max_attempts)[
                :resolved_max_per_tick
            ]
            for session in candidates:
                try:
                    await self.backfill(session.id, force=False)
                    next_session = self.store.get(session.id) or session
                    processed.append(
                        {
                            "sessionId": session.id,
                            "title": session.payload.get("title") or "",
                            "resumeName": (
                                session.payload.get("resume", {}).get("name")
                                or session.payload.get("matchedResume", {}).get("name")
                                or session.candidate_name
                            ),
                            "status": next_session.status,
                            "error": next_session.last_backfill_error,
                        }
                    )
                except Exception as exc:
                    message = str(exc) or "auto backfill failed"
                    processed.append(
                        {
                            "sessionId": session.id,
                            "title": session.payload.get("title") or "",
                            "resumeName": session.candidate_name,
                            "status": "error",
                            "error": message,
                        }
                    )
                    self.store.append_log(session.id, "error", message, {})
            self.last_processed = processed
        except Exception as exc:
            self.last_error = str(exc) or "auto backfill tick failed"
            self.store.append_log("", "error", self.last_error, {})
        finally:
            self.auto_running = False
        return self.status(
            max_per_tick=resolved_max_per_tick,
            max_attempts=resolved_max_attempts,
        )

    def status(
        self,
        *,
        max_per_tick: int | None = None,
        max_attempts: int | None = None,
    ) -> dict[str, Any]:
        """Return old-compatible backfill status."""

        resolved_max_per_tick = max_per_tick or self.max_per_tick
        resolved_max_attempts = max_attempts or self.max_attempts
        return {
            "enabled": self.enabled,
            "running": self.auto_running,
            "intervalMs": self.interval_ms,
            "maxPerTick": resolved_max_per_tick,
            "maxAttempts": resolved_max_attempts,
            "lastRunAt": self.last_run_at,
            "lastError": self.last_error,
            "lastResult": self.last_result,
            "lastProcessed": self.last_processed,
            "inFlightSessionIds": sorted(self.running),
            "runningSessionIds": sorted(self.running),
            "pendingCount": len(self.auto_candidates(max_attempts=resolved_max_attempts)),
        }

    def auto_candidates(self, *, max_attempts: int | None = None) -> list[InterviewSession]:
        """Return sessions eligible for one automatic backfill pass."""

        resolved_max_attempts = max_attempts or self.max_attempts
        now_seconds = int(self.now())
        start_time = now_seconds - 30 * DAY_SECONDS
        end_time = now_seconds + DAY_SECONDS
        candidates: list[InterviewSession] = []
        for session in self.store.list():
            if not session.payload.get("isInterviewLike"):
                continue
            if not session.resume_id:
                continue
            if not session.feishu_doc.get("documentId"):
                continue
            if session.interview_evaluation:
                continue
            if session.id in self.running:
                continue
            if session.status in {
                "non_interview",
                "ignored",
                "completed",
                "needs_review",
                "backfilling",
            }:
                continue
            if int(session.backfill_attempts or 0) >= resolved_max_attempts:
                continue
            session_time = int(session.end_time or session.start_time or 0)
            if not session_time or session_time < start_time or session_time > end_time:
                continue
            if now_seconds < session_time + BACKFILL_DELAY_SECONDS:
                continue
            candidates.append(session)
        return sorted(
            candidates,
            key=lambda item: int(item.end_time or item.start_time or 0),
        )

    def _require_session(self, session_id: str) -> InterviewSession:
        session = self.store.get(session_id)
        if session is None:
            raise KeyError("interview_session_not_found")
        return session

    def _enforce_ten_minute_guard(
        self,
        session: InterviewSession,
        *,
        force: bool,
        early_override: bool,
        early_override_token: str,
    ) -> bool:
        if not session.end_time:
            return False
        available_at = _backfill_available_at(session)
        if int(self.now()) >= available_at:
            return False
        if early_override and force and _is_early_backfill_override_allowed(
            session,
            early_override_token,
            now_seconds=int(self.now()),
        ):
            return True
        if early_override and force:
            raise BackfillError(
                "early_backfill_override_forbidden",
                status_code=403,
            )
        raise BackfillError(
            "backfill_not_available",
            payload={
                "availableAt": available_at,
                "endTime": session.end_time or 0,
            },
        )

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


def _env_enabled(name: str) -> bool:
    return str(getenv(name, "true")).strip().lower() not in {"0", "false", "no"}


def _bounded_int(value: int | None, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    return max(minimum, min(int(value), maximum))


def _backfill_available_at(session: InterviewSession) -> int:
    base_time = int(session.end_time or session.start_time or 0)
    return base_time + BACKFILL_DELAY_SECONDS if base_time else 0


def _is_early_backfill_override_allowed(
    session: InterviewSession,
    token: str,
    *,
    now_seconds: int,
) -> bool:
    override = (
        session.payload.get("earlyBackfillOverride")
        if isinstance(session.payload.get("earlyBackfillOverride"), dict)
        else {}
    )
    if token == session.id:
        return True
    if not override.get("allowed") or override.get("usedAt") or override.get("failedAt"):
        return False
    expected_token = str(override.get("token") or "").strip()
    if not expected_token or expected_token != str(token or "").strip():
        return False
    expires_at = _override_expires_at_seconds(override.get("expiresAt"))
    return not (expires_at and now_seconds > expires_at)


def _used_early_override_payload(
    session: InterviewSession,
    *,
    available_at: int,
    reason: str = "",
) -> dict[str, Any]:
    override = (
        dict(session.payload.get("earlyBackfillOverride"))
        if isinstance(session.payload.get("earlyBackfillOverride"), dict)
        else {}
    )
    return {
        **override,
        "allowed": True,
        "usedAt": now_iso(),
        "availableAt": available_at,
        "reason": str(reason or override.get("reason") or "one_off_manual_override")[:300],
    }


def _override_expires_at_seconds(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, int | float):
        number = int(value)
        return number // 1000 if number > 10_000_000_000 else number
    try:
        normalized = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp())
    except ValueError:
        return 0
