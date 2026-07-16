"""加载知识库和筛选规则。"""

from __future__ import annotations

from app.agent.rules import is_ignored_position, load_chat_rules, select_position_rule
from app.agent.state import GraphState


async def load_rules(state: GraphState) -> GraphState:
    """加载 boss_chat_rules.json 中的规则和岗位 workflow。"""

    rules = state.get("rules") or load_chat_rules()
    if is_ignored_position(str(state.get("applied_position") or ""), rules):
        state["rules"] = rules
        state["stage"] = "ignored_position"
        state["next_action"] = "skip"
        return state
    position_rule = select_position_rule(str(state.get("applied_position") or ""), rules)
    state["rules"] = rules
    if position_rule:
        state["position_rule"] = position_rule
        state["rule_source"] = str(position_rule.get("ruleSource") or "")
        state["stage"] = "rules_loaded"
    else:
        state["stage"] = "unconfigured_position"
        state["next_action"] = "skip"
    return state
