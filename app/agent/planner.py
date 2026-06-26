"""Planner 层。

把用户目标、平台上下文与规则结果路由到 LLM 可见的 function call。
"""

from __future__ import annotations

from app.agent.state import GraphState


def plan_next_action(state: GraphState) -> str:
    """根据当前图状态选择下一步动作名称。"""

    raise NotImplementedError(f"Phase 1 实现 planner，state keys={list(state.keys())}")
