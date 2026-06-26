"""识别候选人匹配的岗位。"""

from __future__ import annotations

from app.agent.state import GraphState


async def identify_job(state: GraphState) -> GraphState:
    """从会话和 JD 规则中识别岗位。"""

    candidate = state.get("candidate") or {}
    position = str(state.get("applied_position") or candidate.get("applied_position") or "")
    state["applied_position"] = position.strip()
    state["stage"] = "job_identified" if position else "job_missing"
    return state
