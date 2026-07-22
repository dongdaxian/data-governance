"""LangGraph 图定义。

构建数据质量检查的工作流图，使用并行节点加速 LLM 调用。

图拓扑：
  START → load_excel → check_basic → ┌─ check_semantic ──┐
                                     └─ normalize_enum ──┘ → combine_results → write_excel → END

check_semantic 和 normalize_enum 并行执行，各自写入独立的状态字段，
combine_results 作为 barrier 节点等待两者完成后汇总。
"""

from langgraph.graph import StateGraph, START, END

from state import GraphState
from nodes import (
    load_excel_node,
    check_basic_node,
    check_semantic_node,
    normalize_enum_node,
    combine_results_node,
    write_excel_node,
)


def build_graph():
    """构建并编译数据质量检查工作流图。"""
    workflow = StateGraph(GraphState)

    # 注册节点
    workflow.add_node("load_excel", load_excel_node)
    workflow.add_node("check_basic", check_basic_node)
    workflow.add_node("check_semantic", check_semantic_node)
    workflow.add_node("normalize_enum", normalize_enum_node)
    workflow.add_node("combine_results", combine_results_node)
    workflow.add_node("write_excel", write_excel_node)

    # 串行边
    workflow.add_edge(START, "load_excel")
    workflow.add_edge("load_excel", "check_basic")

    # 并行扇出：check_basic 完成后同时启动两个 LLM 节点
    workflow.add_edge("check_basic", "check_semantic")
    workflow.add_edge("check_basic", "normalize_enum")

    # 并行汇合：两个 LLM 节点都完成后进入 combine_results（barrier）
    workflow.add_edge("check_semantic", "combine_results")
    workflow.add_edge("normalize_enum", "combine_results")

    # 收尾
    workflow.add_edge("combine_results", "write_excel")
    workflow.add_edge("write_excel", END)

    return workflow.compile()
