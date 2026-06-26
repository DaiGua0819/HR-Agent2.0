"""平台 adapter 抽象接口。"""

from __future__ import annotations

from typing import Protocol

from app.platforms.types import Conversation, ConversationRef, ResumeRequestState, SendResult


class PlatformAdapter(Protocol):
    """所有平台 adapter 需要实现的最小能力。"""

    async def open_chat_page(self) -> None:
        """打开平台聊天页。"""

    async def select_unread_filter(self) -> dict[str, object]:
        """切换到未读筛选。"""

    async def select_positions(self, target_position: str | None = None) -> dict[str, object]:
        """选择全部职位或指定职位。"""

    async def read_unread_conversations(self) -> list[ConversationRef]:
        """读取当前平台未读会话。"""

    async def find_next_unread_thread(self) -> ConversationRef | None:
        """找到下一个未读真实候选人会话。"""

    async def read_chat_context(self) -> Conversation:
        """读取当前会话上下文。"""

    async def send_message(self, message: str) -> SendResult:
        """发送消息并校验最近己方消息。"""

    async def send_company_info(
        self,
        phrase: str = "",
        phrase_key: str = "basic_conditions",
    ) -> SendResult:
        """发送平台配置的公司/基础条件常用语。"""

    async def send_common_phrase(
        self,
        phrase_key: str = "",
        phrase: str = "",
    ) -> SendResult:
        """发送平台常用语。"""

    async def inspect_resume_request_state(self) -> ResumeRequestState:
        """检查当前会话是否已有附件简历或已求过简历。"""

    async def request_resume(self) -> dict[str, object]:
        """点击或触发要附件简历。"""

    async def open_recommend_page(self) -> None:
        """打开推荐人才页。"""

    async def proactive_greet(
        self, target_position: str, dry_run: bool = False
    ) -> dict[str, object]:
        """在推荐页按岗位门槛主动打招呼。"""

    async def mark_unsuitable(self, reason: str = "") -> dict[str, object]:
        """将当前候选人标记为不合适。"""
