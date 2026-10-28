# -*- coding: utf-8 -*-
"""标准维护状态定义 & LLM 结构化输出的 Pydantic Schema。"""

from typing import NotRequired, TypedDict

from pydantic import BaseModel, Field


# ============================================================
# TypedDict -- LangGraph 状态
# ============================================================

class DictEntryItem(TypedDict):
    """单行字典申请单字段及其加工结果（变更标准草稿）。"""
    index: int
    field_name: str           # 输入中文字段名
    field_type: str           # 字段所属类型
    is_enum: str              # 是否枚举（是/否）
    enum_values: str          # 枚举值（码-值;码-值，可为空）
    business_meaning: str     # 输入业务定义

    # 节点产出
    normalized_name: str      # 步骤2：规范化后的中文字段名（未改写=原始名）
    generated_definition: str  # 步骤3：依据规范化名称生成的业务定义
    final_definition: str     # 步骤4：整合原始定义后的最终业务定义
    definition_reason: NotRequired[str]  # 处理提示/失败原因（步骤4未返回时标记需人工复核）


class MaintenanceGraphState(TypedDict):
    """LangGraph 全局状态。"""
    rows: list[DictEntryItem]
    input_file: str
    output_file: str


# ============================================================
# Pydantic Schema -- 用于 LLM with_structured_output
# ============================================================

class NameNormalizeItem(BaseModel):
    """单条中文字段名规范化结果。"""
    row_index: int = Field(description="行号，与输入数据中的row_index对应")
    normalized_name: str = Field(description="规范化后的中文字段名（已规范则与输入一致）")
    changed: bool = Field(description="是否发生了改写（True=原名不规范已改写，False=原名已规范原样保留）")
    reasoning: str = Field(description="简要说明改写依据（中文）")


class NameNormalizeResult(BaseModel):
    """批量中文字段名规范化结果。"""
    results: list[NameNormalizeItem] = Field(description="每行的规范化结果列表")


class DefinitionGenerateItem(BaseModel):
    """单条业务定义生成结果。"""
    row_index: int = Field(description="行号，与输入数据中的row_index对应")
    definition: str = Field(description="依据规范化后的中文字段名生成的业务定义")
    reasoning: str = Field(description="简要说明生成依据（中文）")


class DefinitionGenerateResult(BaseModel):
    """批量业务定义生成结果。"""
    results: list[DefinitionGenerateItem] = Field(description="每行的生成结果列表")


class DefinitionMergeItem(BaseModel):
    """单条业务定义整合结果。"""
    row_index: int = Field(description="行号，与输入数据中的row_index对应")
    final_definition: str = Field(description="整合后的最终业务定义（覆盖生成定义与原始定义全部语义）")
    merged: bool = Field(description="是否发生了补充整合（True=原始定义中有遗漏语义已补充，False=已包含直接采用生成定义）")
    reasoning: str = Field(description="简要说明对照与整合依据（中文）")


class DefinitionMergeResult(BaseModel):
    """批量业务定义整合结果。"""
    results: list[DefinitionMergeItem] = Field(description="每行的整合结果列表")
