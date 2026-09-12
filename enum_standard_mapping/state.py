"""枚举落标处理状态定义。

第 4 步 LLM 判定直接复用 standard_mapping 的 StandardSelectionItem/Result，
本模块只定义 LangGraph 状态所需 TypedDict。
"""

from typing import TypedDict


# ============================================================
# TypedDict -- LangGraph 状态
# ============================================================

class EnumItemDetail(TypedDict):
    """枚举代码候选明细（阶段 1 产出）。"""
    item_id: str            # 枚举代码编号（ENMxxxxx）
    item_name: str          # 标准中文名称（该枚举代码的首个引用标准）
    standards: list[dict]   # 引用该枚举代码的标准清单 [{"std_id", "std_name", "business_definition"}]
    score: int              # 命中条数（满分 n）
    operation: str          # 枚举代码操作：复用 / 修改
    matched_values: list[str]   # 命中码值（码-值，按码值文本匹配）
    missing_values: list[str]   # 缺失码值（字段有、枚举代码没有，可补充）


class FieldToMap(TypedDict):
    """待落标字段及其处理结果。"""
    index: int
    field_name: str           # 字段中文名
    field_type: str           # 字段所属类型（恒为代码枚举类）
    business_meaning: str     # 业务含义
    enum_values: str          # 枚举值文本（质检输出中已规范化覆盖）

    # load_and_score 节点产出
    pairs: list[tuple[str, str]]      # 解析后的 n 条 (码, 值)
    candidates: list[EnumItemDetail]  # 候选枚举代码（召回筛选 Top5）
    candidate_fetch_error: str        # 检索错误信息

    # select_result 节点产出
    mapping_result: str        # 五分类结果之一
    selected_std_id: str       # 选中标准编号
    selected_std_name: str     # 选中标准名称
    enum_code_suggestion: str  # 枚举代码处理建议（修改时填补充清单）
    llm_reason: str            # LLM 判断过程


class EnumMappingGraphState(TypedDict):
    """LangGraph 全局状态。"""
    rows: list[FieldToMap]
    input_file: str
    output_file: str
    selection_results: list[dict]  # select_result 节点产出
    include_candidates: bool       # 是否输出候选及得分明细列
