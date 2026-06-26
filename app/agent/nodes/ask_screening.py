"""筛选问题追问节点。"""

from __future__ import annotations

from app.agent.rules import screening_questions
from app.agent.state import GraphState


async def ask_screening(state: GraphState) -> GraphState:
    """按岗位 workflow 追问必要筛选问题。"""

    rule = state.get("position_rule") or {}
    questions = screening_questions(rule)
    if not questions:
        state["next_action"] = "wait"
        return state
    asked = {
        str(message.get("text") or "")
        for message in state.get("messages", [])
        if message.get("sender") == "me"
    }
    for question in questions:
        if not any(question in item for item in asked):
            state["next_action"] = "ask_screening"
            state["decision"] = {"status": "ask", "reply": question}
            return state
    state["next_action"] = "judge_screening"
    state["decision"] = {"status": "judge", "question": questions[-1]}
    return state
