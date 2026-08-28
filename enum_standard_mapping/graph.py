"""LangGraph 图定义（枚举落标）。

图拓扑：
  START -> load_and_score -> select_result -> write_result -> END
"""

from langgraph.graph import StateGraph, START, END

from enum_standard_mapping.state import EnumMappingGraphState
from enum_standard_mapping.nodes import (
    load_and_score_node,
    select_result_node,
    write_result_node,
)


def build_graph():
    """构建并编译枚举落标工作流图。"""
    workflow = StateGraph(EnumMappingGraphState)

    workflow.add_node("load_and_score", load_and_score_node)
    workflow.add_node("select_result", select_result_node)
    workflow.add_node("write_result", write_result_node)

    workflow.add_edge(START, "load_and_score")
    workflow.add_edge("load_and_score", "select_result")
    workflow.add_edge("select_result", "write_result")
    workflow.add_edge("write_result", END)

    return workflow.compile()
