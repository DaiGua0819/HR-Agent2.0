"""GraphState 定义。

替代旧 `agent_chat_state.json` 的游离状态文件，Phase 1 先由 MemorySaver 持久化。
"""

from __future__ import annotations

from typing import Any, TypedDict


class GraphState(TypedDict, total=False):
    """招聘对话图共享状态。"""

    owner: str
    platform: str
    conversation_id: str
    applied_position: str
    candidate: dict[str, Any]
    rules: dict[str, Any]
    position_rule: dict[str, Any]
    messages: list[dict[str, Any]]
    stage: str
    next_action: str
    decision: dict[str, Any]
    pending_question: str
    conversation_review: dict[str, Any]
    sent_messages: list[str]
    resume_requested: bool
