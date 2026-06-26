"""转人工节点。"""

from __future__ import annotations

from app.agent.state import GraphState


async def escalate(state: GraphState) -> GraphState:
    """记录转人工原因并停止自动回复。"""

    state["stage"] = "escalated"
    state["next_action"] = "escalate"
    return state
