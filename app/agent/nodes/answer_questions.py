"""候选人问题答疑节点。"""

from __future__ import annotations

from app.agent.rules import find_knowledge_answer, looks_like_question
from app.agent.state import GraphState


async def answer_questions(state: GraphState) -> GraphState:
    """根据公司知识库和岗位信息回答候选人问题。"""

    messages = state.get("messages") or []
    last_text = str(messages[-1].get("text") if messages else "")
    if not looks_like_question(last_text):
        return state
    answer = find_knowledge_answer(
        last_text,
        state.get("rules"),
        position=str(state.get("applied_position") or ""),
    )
    if answer:
        state["next_action"] = "answer_question"
        state["decision"] = {"status": "answer", "reply": answer, "evidence": last_text}
    else:
        state["next_action"] = "escalate"
        state["pending_question"] = last_text
        state["decision"] = {"status": "unknown_question", "evidence": last_text}
    return state
