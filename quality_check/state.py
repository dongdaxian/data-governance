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
    normalized_enum: str      # 规范化后的枚举值（写 Excel 时覆盖原枚举值）

    # check_enum_type_consistency 节点产出
    flag_issues: list[str]    # 标志类误用问题列表（码值有且仅有"是"和"否"）

    # combine_results 节点产出
    check_result: str         # "通过" / "不通过"
    fail_reason: str          # 不通过原因汇总

    # soft_check 节点产出
    soft_check_result: str    # 软性检查结果（字段所属类型/枚举值唯一性提示，有提示时非空）


class GraphState(TypedDict):
    """LangGraph 全局状态。"""
    rows: list[RowData]
    input_file: str
    output_file: str
    semantic_results: list[dict]
    enum_results: list[dict]
    data_example_results: list[dict]
    soft_check_results: list[dict]


# ============================================================
# Pydantic Schema -- 用于 LLM with_structured_output
# ============================================================

from pydantic import BaseModel, Field


class BusinessMeaningItem(BaseModel):
    """单行业务含义检查结果。"""
    row_index: int = Field(description="行号，与输入数据中的row_index对应")
    is_meaningful: bool = Field(description="业务含义是否有效。true=有效，false=无效")
    reasoning: str = Field(description="完整的逐步推理过程：必须写明判断依据、比较分析与权衡的逻辑")


class BusinessMeaningResult(BaseModel):
    """批量业务含义检查结果。"""
    results: list[BusinessMeaningItem] = Field(description="每行的检查结果列表")


class EnumNormalizationItem(BaseModel):
    """单行枚举值规范化结果。"""
    row_index: int = Field(description="行号，与输入数据中的row_index对应")
    has_codes: bool = Field(description="输入枚举值是否所有项都提供了代码。任一项缺少代码则为false")
    needs_normalization: bool = Field(description="是否需要规范化（has_codes为true时判断，原始格式已是标准格式则为false）")
    normalized: str = Field(description="规范化后的枚举值，格式为01-成功;02-失败，仅当needs_normalization为true时填写，否则为空字符串")
    reasoning: str = Field(description="完整的逐步推理过程：必须写明判断依据、比较分析与权衡的逻辑")


class EnumNormalizationResult(BaseModel):
    """批量枚举值规范化结果。"""
    results: list[EnumNormalizationItem] = Field(description="每行的规范化结果列表")


class FieldTypeCheckItem(BaseModel):
    """单行字段所属类型检查结果。"""
    row_index: int = Field(description="行号，与输入数据中的row_index对应")
    is_correct: bool = Field(description="当前字段所属类型是否正确。true=正确，false=可能错误")
    correct_type: str = Field(description="判断应为的字段所属类型（六类之一）。is_correct为false时必填")
    reasoning: str = Field(description="完整的逐步推理过程：必须写明判断依据、比较分析与权衡的逻辑")


class FieldTypeCheckResult(BaseModel):
    """批量字段所属类型检查结果。"""
    results: list[FieldTypeCheckItem] = Field(description="每行的检查结果列表")


class EnumAntonymItem(BaseModel):
    """单行代码枚举类/标志类枚举值反义词判断结果。"""
    row_index: int = Field(description="行号，与输入数据中的row_index对应")
    is_antonym: bool = Field(description="枚举值的两项码值是否为反义词。true=反义词，false=不是")
    reasoning: str = Field(description="完整的逐步推理过程：必须写明判断依据、比较分析与权衡的逻辑")


class EnumAntonymResult(BaseModel):
    """批量枚举值反义词判断结果。"""
    results: list[EnumAntonymItem] = Field(description="每行的判断结果列表")


class DataExampleCheckItem(BaseModel):
    """单行数据示例检查结果。"""
    row_index: int = Field(description="行号，与输入数据中的row_index对应")
    is_valid: bool = Field(description="数据示例是否有效。true=有效，false=无效")
    reasoning: str = Field(description="完整的逐步推理过程：必须写明判断依据、比较分析与权衡的逻辑")


class DataExampleCheckResult(BaseModel):
    """批量数据示例语义检查结果。"""
    results: list[DataExampleCheckItem] = Field(description="每行的检查结果列表")
