"""请求附件简历节点。"""

from __future__ import annotations

from app.agent.state import GraphState


async def request_resume(state: GraphState) -> GraphState:
    """要求候选人提供真实附件简历。"""

    state["next_action"] = "request_resume"
    state["resume_requested"] = True
    return state
