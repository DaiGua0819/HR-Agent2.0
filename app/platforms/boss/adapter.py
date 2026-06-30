"""BOSS adapter 编排。"""

from __future__ import annotations

from app.browser.base import BrowserPage
from app.core.constants import Platform
from app.core.dry_run import is_dry_run, record_dry_run_intent
from app.features.interview_invite.platform_actions import invite_to_interview
from app.platforms.boss import actions
from app.platforms.types import Conversation, ConversationRef, ResumeRequestState, SendResult


class BossAdapter:
    """BOSS 平台会话读取与动作入口。"""

    def __init__(self, page: BrowserPage, *, owner: str, dry_run: bool | None = None) -> None:
        self.page = page
        self.owner = owner
        self.dry_run = is_dry_run(dry_run)

    async def open_chat_page(self) -> None:
        await actions.open_chat_page(self.page)

    async def select_unread_filter(self) -> dict[str, object]:
        return await actions.select_unread_filter(self.page)

    async def select_positions(self, target_position: str | None = None) -> dict[str, object]:
        return await actions.select_positions(self.page, target_position)

    async def read_unread_conversations(self) -> list[ConversationRef]:
        return await actions.read_unread_conversations(self.page, owner=self.owner)

    async def find_next_unread_thread(self) -> ConversationRef | None:
        return await actions.find_next_unread_thread(self.page, owner=self.owner)

    async def read_chat_context(self) -> Conversation:
        return await actions.read_chat_context(self.page, owner=self.owner)

    async def send_message(self, message: str) -> SendResult:
        if self.dry_run:
            record_dry_run_intent(
                "boss.send_message",
                owner=self.owner,
                platform="boss",
                message=message,
            )
            return SendResult(sent=False, verified=False, blocked=False, message="dry_run")
        return await actions.send_message(self.page, message)

    async def send_company_info(
        self,
        phrase: str = "",
        phrase_key: str = "basic_conditions",
    ) -> SendResult:
        if self.dry_run:
            record_dry_run_intent(
                "boss.send_company_info",
                owner=self.owner,
                platform="boss",
                phrase=phrase,
                phraseKey=phrase_key,
            )
            return SendResult(sent=False, verified=False, blocked=False, message="dry_run")
        return await actions.send_company_info(
            self.page,
            phrase=phrase,
            phrase_key=phrase_key,
        )

    async def send_common_phrase(
        self,
        phrase_key: str = "",
        phrase: str = "",
    ) -> SendResult:
        if self.dry_run:
            record_dry_run_intent(
                "boss.send_common_phrase",
                owner=self.owner,
                platform="boss",
                phrase=phrase,
                phraseKey=phrase_key,
            )
            return SendResult(sent=False, verified=False, blocked=False, message="dry_run")
        return await actions.send_common_phrase(
            self.page,
            phrase_key=phrase_key,
            phrase=phrase,
        )

    async def inspect_resume_request_state(self) -> ResumeRequestState:
        return await actions.inspect_resume_request_state(self.page)

    async def request_resume(self) -> dict[str, object]:
        if self.dry_run:
            record_dry_run_intent("boss.request_resume", owner=self.owner, platform="boss")
            return {"requested": False, "dryRun": True}
        return await actions.request_resume(self.page)

    async def invite_to_interview(self, payload: dict[str, object]) -> dict[str, object]:
        return await invite_to_interview(
            self.page,
            platform=Platform.BOSS,
            owner=self.owner,
            payload=dict(payload),
            send_message=self.send_message,
            dry_run=self.dry_run or bool(payload.get("dryRun")),
        )

    async def open_recommend_page(self) -> None:
        await actions.open_recommend_page(self.page)

    async def proactive_greet(
        self, target_position: str, dry_run: bool = False
    ) -> dict[str, object]:
        dry_run = self.dry_run or dry_run
        return await actions.proactive_greet(
            self.page,
            target_position=target_position,
            dry_run=dry_run,
        )

    async def mark_unsuitable(self, reason: str = "") -> dict[str, object]:
        if self.dry_run:
            record_dry_run_intent(
                "boss.mark_unsuitable",
                owner=self.owner,
                platform="boss",
                reason=reason,
            )
            return {"marked": False, "dryRun": True, "reason": reason}
        return await actions.mark_unsuitable(self.page, reason=reason)
