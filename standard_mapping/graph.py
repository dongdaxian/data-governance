"""LangGraph 图定义。

构建落标处理的工作流图。

图拓扑：
  START -> load_and_fetch -> check_domain -> select_standard -> write_result -> END

串行执行，每个节点处理完后将结果传递给下一个节点。
"""

from langgraph.graph import StateGraph, START, END

from standard_mapping.state import MappingGraphState
from standard_mapping.nodes import (
    load_and_fetch_node,
    check_domain_node,
    select_standard_node,
    write_result_node,
)


def build_graph():
    """构建并编译落标处理工作流图。"""
    workflow = StateGraph(MappingGraphState)

    # 注册节点
    workflow.add_node("load_and_fetch", load_and_fetch_node)
    workflow.add_node("check_domain", check_domain_node)
    workflow.add_node("select_standard", select_standard_node)
    workflow.add_node("write_result", write_result_node)

    # 串行边
    workflow.add_edge(START, "load_and_fetch")
    workflow.add_edge("load_and_fetch", "check_domain")
    workflow.add_edge("check_domain", "select_standard")
    workflow.add_edge("select_standard", "write_result")
    workflow.add_edge("write_result", END)

    return workflow.compile()
