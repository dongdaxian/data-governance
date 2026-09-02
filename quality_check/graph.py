# -*- coding: utf-8 -*-
"""LangGraph 图定义。

构建数据质量检查的工作流图。

图拓扑：
  START -> load_excel -> check_rules -> normalize_enum -> check_semantic -> check_flag -> combine_results -> write_excel -> END

normalize_enum 和 check_semantic 串行执行，各自写入独立的状态字段，
check_flag 在两者完成后执行标志类误用检查，
combine_results 作为 barrier 节点汇总。
"""

from langgraph.graph import StateGraph, START, END

from quality_check.state import GraphState
from quality_check.nodes import (
    load_excel_node,
    check_rules_node,
    check_semantic_node,
    normalize_enum_node,
    check_flag_node,
    combine_results_node,
    write_excel_node,
)


def build_graph():
    """构建并编译数据质量检查工作流图。"""
    workflow = StateGraph(GraphState)

    # 注册节点
    workflow.add_node("load_excel", load_excel_node)
    workflow.add_node("check_rules", check_rules_node)
    workflow.add_node("check_semantic", check_semantic_node)
    workflow.add_node("normalize_enum", normalize_enum_node)
    workflow.add_node("check_flag", check_flag_node)
    workflow.add_node("combine_results", combine_results_node)
    workflow.add_node("write_excel", write_excel_node)

    # 串行边
    workflow.add_edge(START, "load_excel")
    workflow.add_edge("load_excel", "check_rules")
    workflow.add_edge("check_rules", "normalize_enum")
    workflow.add_edge("normalize_enum", "check_semantic")

    # 收尾
    workflow.add_edge("check_semantic", "check_flag")
    workflow.add_edge("check_flag", "combine_results")
    workflow.add_edge("combine_results", "write_excel")
    workflow.add_edge("write_excel", END)

    return workflow.compile()
