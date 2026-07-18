"""51job adapter 编排。"""

from __future__ import annotations

from app.browser.base import BrowserPage
from app.core.constants import Platform
from app.core.dry_run import is_dry_run, record_dry_run_intent
from app.features.interview_invite.platform_actions import invite_to_interview
from app.platforms.job51 import actions_chat, actions_recommend, actions_resume
from app.platforms.types import Conversation, ConversationRef, ResumeRequestState, SendResult


class Job51Adapter:
    """51job 平台会话读取与动作入口。"""

    def __init__(self, page: BrowserPage, *, owner: str, dry_run: bool | None = None) -> None:
        self.page = page
        self.owner = owner
        self.dry_run = is_dry_run(dry_run)
        self._pending_send_identity: dict[str, object] | None = None
        self._conversation_snapshot: Conversation | None = None

    async def open_chat_page(self) -> None:
        await actions_chat.open_chat_page(self.page)

    async def select_unread_filter(self) -> dict[str, object]:
        return await actions_chat.select_unread_filter(self.page)

    async def select_positions(self, target_position: str | None = None) -> dict[str, object]:
        return await actions_chat.select_positions(self.page, target_position)

    async def read_unread_conversations(self) -> list[ConversationRef]:
        return await actions_chat.read_unread_conversations(self.page, owner=self.owner)

    async def find_next_unread_thread(
        self,
        *,
        exclude_ids: set[str] | None = None,
    ) -> ConversationRef | None:
        self._conversation_snapshot = None
        return await actions_chat.find_next_thread(
            self.page,
            owner=self.owner,
            exclude_ids=exclude_ids,
        )

    async def read_chat_context(self) -> Conversation:
        if self._conversation_snapshot is None:
            self._conversation_snapshot = await actions_chat.read_chat_context(
                self.page,
                owner=self.owner,
            )
        return self._conversation_snapshot

    async def send_message(self, message: str) -> SendResult:
        if self.dry_run:
            record_dry_run_intent(
                "job51.send_message",
                owner=self.owner,
                platform="job51",
                message=message,
            )
            return SendResult(sent=False, verified=False, blocked=False, message="dry_run")
        expected_identity = self._pending_send_identity
        try:
            return await actions_chat.send_message(
                self.page,
                message,
                expected_identity=expected_identity,
            )
        finally:
            if expected_identity is not None:
                self._pending_send_identity = None

    async def send_company_info(
        self,
        phrase: str = "",
        phrase_key: str = "basic_conditions",
    ) -> SendResult:
        _ = phrase_key
        if not phrase:
            return SendResult(sent=False, blocked=True, message="51job 未配置基础条件话术")
        return await self.send_message(phrase)

    async def send_common_phrase(
        self,
        phrase_key: str = "",
        phrase: str = "",
    ) -> SendResult:
        _ = phrase_key
        if not phrase:
            return SendResult(sent=False, blocked=True, message="51job 不支持空常用语发送")
        return await self.send_message(phrase)

    async def inspect_resume_request_state(self) -> ResumeRequestState:
        return await actions_resume.inspect_resume_request_state(self.page)

    async def request_resume(self) -> dict[str, object]:
        if self.dry_run:
            record_dry_run_intent("job51.request_resume", owner=self.owner, platform="job51")
            return {"requested": False, "downloaded": False, "dryRun": True}
        conversation = await self.read_chat_context()
        self._pending_send_identity = {
            "name": conversation.candidate.name,
            "position": conversation.candidate.applied_position,
            "label": conversation.id,
            "latest_message": conversation.latest_message,
        }
        try:
            return await actions_resume.request_or_download_resume(
                self.page,
                candidate_name=conversation.candidate.name,
                applied_position=conversation.candidate.applied_position,
            )
        finally:
            self._pending_send_identity = None

    async def invite_to_interview(self, payload: dict[str, object]) -> dict[str, object]:
        return await invite_to_interview(
            self.page,
            platform=Platform.JOB51,
            owner=self.owner,
            payload=dict(payload),
            send_message=self.send_message,
            dry_run=self.dry_run or bool(payload.get("dryRun")),
        )

    async def open_recommend_page(self) -> None:
        await actions_recommend.open_recommend_page(self.page)

    async def proactive_greet(
        self, target_position: str, dry_run: bool = False
    ) -> dict[str, object]:
        dry_run = self.dry_run or dry_run
        return await actions_recommend.proactive_greet(
            self.page,
            target_position=target_position,
            dry_run=dry_run,
        )

    async def mark_unsuitable(self, reason: str = "") -> dict[str, object]:
        return {"marked": False, "reason": reason or "job51_not_supported_in_phase3"}
