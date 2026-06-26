"""主动联系候选人节点。"""

from __future__ import annotations

from app.agent.state import GraphState


async def proactive_contact(state: GraphState) -> GraphState:
    """按岗位门槛生成主动打招呼消息。"""

    state["next_action"] = "proactive_contact"
    return state
