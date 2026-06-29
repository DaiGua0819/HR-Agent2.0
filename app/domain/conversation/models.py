"""候选人会话状态模型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConversationSession:
    """平台候选人会话的稳定业务身份。"""

    id: str
    platform: str
    owner: str
    candidate_name: str
    position: str
    applied_position: str = ""
    platform_conversation_id: str = ""
    label: str = ""
    current_stage: str = ""
    next_action: str = ""
    recent_messages_fingerprint: str = ""
    identity_confidence: str = ""
    identity_warnings: list[str] = field(default_factory=list)
    last_seen_at: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class ConversationMessageRecord:
    """已持久化的聊天消息。"""

    id: str
    session_id: str
    sender: str
    text: str
    raw_text: str
    sent_at: str
    platform_message_id: str
    message_hash: str
    created_at: str


@dataclass(frozen=True)
class CandidateStatus:
    """候选人在某平台会话上的长期处理状态。"""

    session_id: str
    asked_questions: list[str] = field(default_factory=list)
    resume_requested: bool = False
    resume_received: bool = False
    resume_downloaded: bool = False
    resume_path: str = ""
    last_action: str = ""
    next_question: str = ""
    decided_result: str = ""
    payload: dict[str, object] = field(default_factory=dict)
    updated_at: str = ""


@dataclass(frozen=True)
class SessionResolution:
    """身份定位结果。"""

    session: ConversationSession
    confidence: str
    warnings: list[str] = field(default_factory=list)

