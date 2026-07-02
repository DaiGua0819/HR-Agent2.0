"""Meeting/minutes source collection boundary for interview backfill."""

from __future__ import annotations

from typing import Any, Protocol

from app.features.interview_center.store import InterviewSession


class MeetingSourceClientProtocol(Protocol):
    """Collect text sources that can be used for interview evaluation backfill."""

    async def collect_sources(self, session: InterviewSession) -> dict[str, Any]:
        """Return collected text and public source metadata."""


class EmptyMeetingSourceClient:
    """Safe default until the real Feishu VC/minutes client is wired."""

    async def collect_sources(self, session: InterviewSession) -> dict[str, Any]:
        return {
            "text": "",
            "source": {
                "source": "empty",
                "sessionId": session.id,
                "errors": ["meeting_source_client_not_configured"],
            },
        }
