"""落标处理状态定义 & LLM 结构化输出的 Pydantic Schema。"""

from typing import TypedDict

from pydantic import BaseModel, Field


# ============================================================
# TypedDict -- LangGraph 状态
# ============================================================

class CandidateStandard(TypedDict):
    """备选标准信息。"""
    std_id: str           # 标准编号
    std_name: str         # 标准名称
    std_type: str         # 标准所属类型
    business_definition: str  # 业务定义
    domain_id: str        # 域编号
    domain_name: str      # 域名称
    domain_type: str      # 域类型（如 an..(20)）
    data_example: str     # 数据示例


class FieldToMap(TypedDict):
    """待落标字段及其处理结果。"""
    index: int
    field_name: str           # 字段中文名
    field_type: str           # 字段所属类型
    business_meaning: str     # 业务含义
    enum_values: str          # 枚举值
    data_example: str         # 数据示例（申请单上）

    # load_and_fetch 节点产出
    candidates: list[CandidateStandard]  # 备选标准列表

    # check_domain 节点产出
    domain_check_details: str  # 域检查详情

    # select_standard 节点产出
    mapping_result: str        # "复用已有标准" / "复用已有标准但扩展业务定义" / "新增标准"
    selected_std_id: str       # 选中标准编号
    selected_std_name: str     # 选中标准名称
    llm_reason: str            # LLM 判断过程


class MappingGraphState(TypedDict):
    """LangGraph 全局状态。"""
    rows: list[FieldToMap]
    input_file: str
    output_file: str
    domain_results: list[dict]     # check_domain 节点产出
    selection_results: list[dict]  # select_standard 节点产出


# ============================================================
# Pydantic Schema -- 用于 LLM with_structured_output
# ============================================================

class StandardSelectionItem(BaseModel):
    """单条标准选择结果。"""
    row_index: int = Field(description="行号，与输入数据中的row_index对应")
    selection: str = Field(description="选择结果：复用已有标准 / 复用已有标准但扩展业务定义 / 新增标准")
    selected_std_id: str = Field(default="", description="选中的标准编号")
    selected_std_name: str = Field(default="", description="选中的标准名称")
    extension_suggestion: str = Field(default="", description="扩展业务定义建议（仅当选择'复用已有标准但扩展业务定义'时填写）")
    reason: str = Field(description="判断过程和原因说明，需详细描述比较分析的过程")


class StandardSelectionResult(BaseModel):
    """批量标准选择结果。"""
    results: list[StandardSelectionItem] = Field(description="每行的标准选择结果列表")
