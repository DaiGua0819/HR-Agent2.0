"""筛选问题追问节点。"""

from __future__ import annotations

from app.agent.rules import rule_screening
from app.agent.screening import analyze_position_screening, select_position_screening_question_text
from app.agent.state import GraphState


async def ask_screening(state: GraphState) -> GraphState:
    """按岗位 workflow 追问必要筛选问题。"""

    rule = state.get("position_rule") or {}
    screening = rule_screening(rule)
    if not screening:
        state["next_action"] = "wait"
        return state
    analysis = await analyze_position_screening(state.get("messages", []), screening)
    state["screening_analysis"] = analysis
    if analysis.get("status") == "not_asked":
        question = (
            analysis.get("nextQuestion")
            if isinstance(analysis.get("nextQuestion"), dict)
            else {}
        )
        reply = select_position_screening_question_text(question)
        state["next_action"] = "ask_screening"
        state["decision"] = {"status": "ask", "reply": reply, "screening": analysis}
        return state
    state["next_action"] = "judge_screening"
    state["decision"] = {"status": analysis.get("status"), "screening": analysis}
    return state
