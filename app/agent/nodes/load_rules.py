"""加载知识库和筛选规则。"""

from __future__ import annotations

from app.agent.rules import load_chat_rules, select_position_rule
from app.agent.state import GraphState


async def load_rules(state: GraphState) -> GraphState:
    """加载 boss_chat_rules.json 中的规则和岗位 workflow。"""

    rules = state.get("rules") or load_chat_rules()
    position_rule = select_position_rule(str(state.get("applied_position") or ""), rules)
    state["rules"] = rules
    if position_rule:
        state["position_rule"] = position_rule
        state["stage"] = "rules_loaded"
    else:
        state["stage"] = "unconfigured_position"
        state["next_action"] = "skip"
    return state
