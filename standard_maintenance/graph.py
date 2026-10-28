# -*- coding: utf-8 -*-
"""LangGraph 图定义（标准维护）。

图拓扑：
  START -> load -> normalize -> generate -> merge -> write -> END
"""

from langgraph.graph import StateGraph, START, END

from standard_maintenance.state import MaintenanceGraphState
from standard_maintenance.nodes import (
    load_node,
    normalize_node,
    generate_node,
    merge_node,
    write_node,
)


def build_graph():
    """构建并编译标准维护工作流图。"""
    workflow = StateGraph(MaintenanceGraphState)

    workflow.add_node("load", load_node)
    workflow.add_node("normalize", normalize_node)
    workflow.add_node("generate", generate_node)
    workflow.add_node("merge", merge_node)
    workflow.add_node("write", write_node)

    workflow.add_edge(START, "load")
    workflow.add_edge("load", "normalize")
    workflow.add_edge("normalize", "generate")
    workflow.add_edge("generate", "merge")
    workflow.add_edge("merge", "write")
    workflow.add_edge("write", END)

    return workflow.compile()
