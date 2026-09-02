# -*- coding: utf-8 -*-
"""LangGraph 状态定义 & LLM 结构化输出的 Pydantic Schema。"""

from typing import TypedDict


class RowData(TypedDict):
    """单行数据及其检查结果。"""
    index: int
    table_name: str           # 中文表名
    field_name: str           # 中文字段名
    field_type: str           # 字段所属类型
    domain_type: str          # 域类型
    data_example: str         # 数据示例
    is_enum: str              # 是否枚举（"是"/"否"）
    business_meaning: str     # 业务定义
    enum_values: str          # 枚举值（原始）

    # check_rules 节点产出
    rule_issues: list[str]    # 规则检查问题列表
    rule_passed: bool         # 规则检查是否全部通过

    # check_semantic 节点产出
    is_meaningful: bool       # 业务含义是否有效
    meaning_reason: str       # LLM 判断过程

    # normalize_enum 节点产出
    normalized_enum: str      # 规范化后的枚举值
    enum_needs_normalization: bool  # 是否进行了规范化

    # check_flag 节点产出
    flag_issues: list[str]    # 标志类误用问题列表（码值有且仅有"是"和"否"）

    # combine_results 节点产出
    check_result: str         # "通过" / "不通过"
    fail_reason: str          # 不通过原因汇总


class GraphState(TypedDict):
    """LangGraph 全局状态。"""
    rows: list[RowData]
    input_file: str
    output_file: str
    semantic_results: list[dict]
    enum_results: list[dict]


# ============================================================
# Pydantic Schema -- 用于 LLM with_structured_output
# ============================================================

from pydantic import BaseModel, Field


class BusinessMeaningItem(BaseModel):
    """单行业务含义检查结果。"""
    row_index: int = Field(description="行号，与输入数据中的row_index对应")
    is_meaningful: bool = Field(description="业务含义是否有效。true=有效，false=无效")
    reason: str = Field(description="判断过程和原因说明，需详细描述比较分析的过程")


class BusinessMeaningResult(BaseModel):
    """批量业务含义检查结果。"""
    results: list[BusinessMeaningItem] = Field(description="每行的检查结果列表")


class EnumNormalizationItem(BaseModel):
    """单行枚举值规范化结果。"""
    row_index: int = Field(description="行号，与输入数据中的row_index对应")
    normalized: str = Field(description="规范化后的枚举值，格式为01-成功;02-失败")
    needs_normalization: bool = Field(description="是否需要规范化。如果原始格式已是标准格式则为false")


class EnumNormalizationResult(BaseModel):
    """批量枚举值规范化结果。"""
    results: list[EnumNormalizationItem] = Field(description="每行的规范化结果列表")
