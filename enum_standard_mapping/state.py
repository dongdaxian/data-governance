"""枚举落标处理状态定义 & LLM 结构化输出的 Pydantic Schema。"""

from typing import NotRequired, TypedDict

from pydantic import BaseModel, Field

from enum_standard_mapping.constants import ALL_RESULTS


# ============================================================
# TypedDict -- LangGraph 状态
# ============================================================

class EnumItemDetail(TypedDict):
    """枚举值项候选明细（阶段 1 产出）。"""
    item_id: str            # 域编号（domain）或标准编号（standard/name）
    item_type: str          # domain / standard
    item_name: str          # 域名称或标准名称
    standards: list[dict]   # 名下字典清单 [{"std_id": ..., "std_name": ...}]
    score: int              # 命中条数（满分 n）
    matched_values: list[str]   # 命中码值（码-值）
    missing_values: list[str]   # 缺失码值（字段有、域没有，可补充）
    conflict_values: list[str]  # 码冲突（域中该码已被占用且值不同，不可补充）
    item_pairs: list[tuple[str, str]]  # 域内全部码值对（LLM 对比用）


class FieldToMap(TypedDict):
    """待落标字段及其处理结果。"""
    index: int
    field_name: str           # 字段中文名
    field_type: str           # 字段所属类型（恒为代码枚举类）
    business_meaning: str     # 业务含义
    enum_values: str          # 原始格式化枚举值文本

    # load_and_score 节点产出
    pairs: list[tuple[str, str]]      # 解析后的 n 条 (码, 值)
    candidates: list[EnumItemDetail]  # 候选枚举值项（Top20 含并列）
    degraded_name_hits: list[dict]    # 降级名称检索命中（仅零候选时填充）
    candidate_fetch_error: str        # 检索错误信息

    # select_result 节点产出
    mapping_result: str        # 七分类结果之一
    selected_std_id: str       # 选中标准编号
    selected_std_name: str     # 选中标准名称
    domain_action: str         # 域处理建议（补充/新建/挂靠等）
    conflict_detail: str       # 结果 6 的冲突候选及枚举值对比
    llm_reason: str            # LLM 判断过程


class EnumMappingGraphState(TypedDict):
    """LangGraph 全局状态。"""
    rows: list[FieldToMap]
    input_file: str
    output_file: str
    selection_results: list[dict]  # select_result 节点产出
    include_candidates: bool       # 是否输出候选及得分明细列


# ============================================================
# Pydantic Schema -- 用于 LLM with_structured_output
# ============================================================

_RESULT_DESC = " / ".join(ALL_RESULTS)


class EnumSelectionItem(BaseModel):
    """单条枚举落标结果。"""
    row_index: int = Field(description="行号，与输入数据中的row_index对应")
    selection: str = Field(description=f"落标结果，必须是以下七个值之一: {_RESULT_DESC}")
    selected_std_id: str = Field(default="", description="选中的标准编号（新增标准时留空）")
    selected_std_name: str = Field(default="", description="选中的标准名称（新增标准时留空）")
    domain_action: str = Field(
        default="",
        description=(
            "域处理建议："
            "结果1复用时留空；"
            "结果2填'复用域<域编号>'；"
            "结果3填'新增域'；"
            "结果4/5填需补充的码值清单（如'向域CDE00001补充: 9-小程序, 23-远程银行'，码冲突值不可补充需注明）；"
            "结果6/7按判定填写"
        ),
    )
    conflict_detail: str = Field(
        default="",
        description="仅结果6填写：冲突候选标准及双方枚举值差异对比，供人工裁决",
    )
    reason: str = Field(description="判断过程和原因说明，需详细描述比较分析的过程")


class EnumSelectionResult(BaseModel):
    """批量枚举落标结果。"""
    results: list[EnumSelectionItem] = Field(description="每行的落标结果列表")
