"""跨平台标准化类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.core.constants import Platform


class MessageSender(StrEnum):
    """标准化消息发送方。"""

    ME = "me"
    CANDIDATE = "other"
    SYSTEM = "system"


@dataclass(frozen=True)
class ChatMessage:
    """标准化聊天消息。"""

    sender: MessageSender
    text: str
    raw_text: str = ""
    time: str = ""


@dataclass(frozen=True)
class Candidate:
    """标准化候选人信息。"""

    name: str
    applied_position: str
    label: str = ""
    source: str = ""


@dataclass(frozen=True)
class ConversationRef:
    """标准化会话引用。"""

    platform: Platform
    owner: str
    conversation_id: str


@dataclass(frozen=True)
class Conversation:
    """平台会话上下文。"""

    id: str
    platform: Platform
    owner: str
    candidate: Candidate
    messages: list[ChatMessage]
    unread_count: int = 0
    latest_message: str = ""
    should_reply: bool = False


@dataclass(frozen=True)
class ResumeRequestState:
    """当前会话附件简历状态。"""

    has_resume_attachment: bool = False
    already_requested: bool = False
    pending_resume_consent: bool = False
    summary: str = ""


@dataclass(frozen=True)
class SendResult:
    """发送消息结果。"""

    sent: bool
    verified: bool = False
    blocked: bool = False
    message: str = ""
    details: dict[str, object] = field(default_factory=dict)
