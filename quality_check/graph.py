# -*- coding: utf-8 -*-
"""LangGraph 图定义。

构建数据质量检查的工作流图。

图拓扑：
  START -> load_excel -> check_rules -> normalize_enum -> check_semantic -> check_enum_type_consistency -> combine_results -> soft_check -> write_excel -> END

normalize_enum 和 check_semantic 串行执行，各自写入独立的状态字段，
check_enum_type_consistency 在两者完成后执行字段类型与枚举值一致性检查，
combine_results 作为 barrier 节点汇总，
soft_check 在汇总后执行软性检查（字段所属类型/枚举值唯一性/枚举值反义词，不影响检查结果列）。
"""

from langgraph.graph import StateGraph, START, END

from quality_check.state import GraphState
from quality_check.nodes import (
    load_excel_node,
    check_rules_node,
    check_semantic_node,
    normalize_enum_node,
    check_enum_type_consistency_node,
    combine_results_node,
    soft_check_node,
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
    workflow.add_node("check_enum_type_consistency", check_enum_type_consistency_node)
    workflow.add_node("combine_results", combine_results_node)
    workflow.add_node("soft_check", soft_check_node)
    workflow.add_node("write_excel", write_excel_node)

    # 串行边
    workflow.add_edge(START, "load_excel")
    workflow.add_edge("load_excel", "check_rules")
    workflow.add_edge("check_rules", "normalize_enum")
    workflow.add_edge("normalize_enum", "check_semantic")

    # 收尾
    workflow.add_edge("check_semantic", "check_enum_type_consistency")
    workflow.add_edge("check_enum_type_consistency", "combine_results")
    workflow.add_edge("combine_results", "soft_check")
    workflow.add_edge("soft_check", "write_excel")
    workflow.add_edge("write_excel", END)

    return workflow.compile()
