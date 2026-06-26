"""LangGraph 装配入口。"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agent.checkpointer import get_checkpointer
from app.agent.nodes.identify_job import identify_job
from app.agent.nodes.load_rules import load_rules
from app.agent.state import GraphState


def build_recruit_graph():
    """构建平台无关的最小招聘对话图。"""

    graph = StateGraph(GraphState)
    graph.add_node("identify_job", identify_job)
    graph.add_node("load_rules", load_rules)
    graph.set_entry_point("identify_job")
    graph.add_edge("identify_job", "load_rules")
    graph.add_edge("load_rules", END)
    return graph.compile(checkpointer=get_checkpointer())
