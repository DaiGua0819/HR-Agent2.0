"""Calendar synchronization orchestration for the interview center."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.domain.resume.repository import ResumeRepository
from app.features.interview_center.candidate_matcher import (
    decide_calendar_auto_binding,
    match_calendar_event_candidates,
)
from app.features.interview_center.feishu.calendar import normalize_calendar_event
from app.features.interview_center.feishu.client import (
    FEISHU_BASE_URL,
    FeishuUserTokenProvider,
)
from app.features.interview_center.store import InterviewSession, InterviewStoreProtocol, now_iso

DAY_SECONDS = 24 * 60 * 60


class CalendarClientProtocol(Protocol):
    """Minimal calendar client contract used by the sync service."""

    async def list_events(
        self,
        *,
        calendar_id: str,
        start_time: int,
        end_time: int,
    ) -> list[dict[str, Any]]:
        """List raw Feishu calendar events."""


class EmptyCalendarClient:
    """Safe default calendar client used until OAuth-backed client lands."""

    async def list_events(
        self,
        *,
        calendar_id: str,
        start_time: int,
        end_time: int,
    ) -> list[dict[str, Any]]:
        _ = calendar_id, start_time, end_time
        return []


@dataclass
class FeishuCalendarClient:
    """OAuth-backed Feishu calendar reader."""

    token_provider: FeishuUserTokenProvider
    base_url: str = FEISHU_BASE_URL
    transport: httpx.AsyncBaseTransport | None = None
    skip_without_token: bool = True

    async def list_events(
        self,
        *,
        calendar_id: str,
        start_time: int,
        end_time: int,
    ) -> list[dict[str, Any]]:
        user_token = await self.token_provider.user_access_token()
        if not user_token:
            if self.skip_without_token:
                return []
            raise ValueError("feishu_user_token_required")
        events: list[dict[str, Any]] = []
        page_token = ""
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30,
            transport=self.transport,
        ) as client:
            while True:
                params = {
                    "page_size": "50",
                    "start_time": str(start_time),
                    "end_time": str(end_time),
                }
                if page_token:
                    params["page_token"] = page_token
                response = await client.get(
                    f"/calendar/v4/calendars/{calendar_id}/events",
                    headers={"Authorization": f"Bearer {user_token}"},
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
                if int(payload.get("code") or 0) != 0:
                    raise ValueError(str(payload.get("msg") or "feishu_calendar_list_failed"))
                data = payload.get("data") or {}
                events.extend(list(data.get("items") or data.get("events") or []))
                page_token = str(data.get("page_token") or data.get("next_page_token") or "")
                if not data.get("has_more") or not page_token:
                    break
        return events


class CalendarSyncService:
    """Sync Feishu calendar events into interview sessions."""

    def __init__(
        self,
        *,
        store: InterviewStoreProtocol,
        repository: ResumeRepository,
        calendar_client: CalendarClientProtocol | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.store = store
        self.repository = repository
        self.calendar_client = calendar_client or EmptyCalendarClient()
        self.now = now or time.time
        self.running = False
        self.last_run_at = ""
        self.last_error = ""
        self.last_result: dict[str, Any] | None = None

    async def sync(
        self,
        *,
        calendar_id: str = "primary",
        auto_prepare: bool = False,
        auto_prepare_limit: int = 12,
        source: str = "manual",
        skip_if_running: bool = False,
    ) -> dict[str, Any]:
        """Synchronize calendar events and return an old-compatible payload."""

        _ = auto_prepare, auto_prepare_limit
        if self.running:
            if skip_if_running:
                return self._skipped_running_result()
            raise RuntimeError("calendar_sync_running")
        self.running = True
        self.last_run_at = now_iso()
        self.last_error = ""
        start_time = int(self.now()) - DAY_SECONDS
        end_time = start_time + 15 * DAY_SECONDS
        try:
            raw_events = await self.calendar_client.list_events(
                calendar_id=calendar_id,
                start_time=start_time,
                end_time=end_time,
            )
            resumes = list(self.repository.iter_resumes())
            synced: list[InterviewSession] = []
            for raw_event in raw_events:
                event = normalize_calendar_event(calendar_id, raw_event)
                session = self.store.upsert_from_calendar_event(event)
                if event["isInterviewLike"]:
                    session = self._match_and_save_session(session, event, resumes)
                synced.append(session)
            interview_sessions = [
                session.to_dict()
                for session in synced
                if bool(session.payload.get("isInterviewLike"))
            ]
            result = {
                "range": {"startTime": start_time, "endTime": end_time},
                "total": len(raw_events),
                "interviewLike": len(interview_sessions),
                "prepared": 0,
                "prepareErrors": [],
                "bitableResumeResults": [],
                "sessions": interview_sessions,
            }
            self.last_result = {
                "source": source,
                "total": result["total"],
                "interviewLike": result["interviewLike"],
                "prepared": 0,
                "prepareErrors": 0,
                "range": result["range"],
                "syncedAt": self.last_run_at,
            }
            self.store.append_log(
                "",
                "info",
                f"{source} calendar sync completed",
                {
                    "source": source,
                    "total": result["total"],
                    "interviewLike": result["interviewLike"],
                    "prepared": 0,
                },
            )
            return result
        except Exception as exc:
            self.last_error = str(exc)
            raise
        finally:
            self.running = False

    def status(self) -> dict[str, Any]:
        """Return old-compatible calendar sync status."""

        return {
            "enabled": True,
            "running": self.running,
            "lastRunAt": self.last_run_at,
            "lastError": self.last_error,
            "lastResult": self.last_result,
        }

    def _match_and_save_session(
        self,
        session: InterviewSession,
        event: dict[str, Any],
        resumes: list[Any],
    ) -> InterviewSession:
        matches = match_calendar_event_candidates(event, resumes)
        decision = decide_calendar_auto_binding(matches)
        session.matches = [
            {
                "resumeId": match["resumeId"],
                "name": match["name"],
                "jobType": match["jobType"],
                "score": match["score"],
                "reasons": match["reasons"],
                "exactIdentityMatch": match["exactIdentityMatch"],
            }
            for match in matches
        ]
        session.payload = {
            **session.payload,
            "matchCandidates": session.matches,
            "matchDecision": decision,
        }
        if decision.get("bind") and decision.get("match"):
            match = decision["match"]
            session.resume_id = str(match["resumeId"])
            session.candidate_name = str(match["name"])
            session.job_type = str(match["jobType"])
            session.status = "matched"
            session.payload = {
                **session.payload,
                "resumeId": session.resume_id,
                "matchMode": "auto",
                "matchedResume": {
                    "id": session.resume_id,
                    "name": session.candidate_name,
                    "jobType": session.job_type,
                },
            }
        elif not session.resume_id:
            session.status = str(decision.get("status") or "needs_confirmation")
        return self.store.save(session)

    def _skipped_running_result(self) -> dict[str, Any]:
        return {
            "skipped": True,
            "reason": "calendar_sync_running",
            "range": None,
            "total": 0,
            "interviewLike": 0,
            "prepared": 0,
            "prepareErrors": [],
            "bitableResumeResults": [],
            "sessions": [],
        }
