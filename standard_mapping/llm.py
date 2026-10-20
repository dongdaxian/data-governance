"""落标处理 -- 模块专用 LLM 调用。

包含标准选择的 LLM 调用逻辑。
"""

import json
from collections import defaultdict

from config import STANDARD_MAPPING_BATCH_SIZE as BATCH_SIZE

from langchain_openai import ChatOpenAI

from common.llm_client import get_llm, call_with_retry, chunked
from standard_mapping.state import (
    StandardSelectionResult,
    FieldNameRewriteResult,
)
from standard_mapping.prompts import (
    STANDARD_SELECTION_COMMON,
    STANDARD_SELECTION_EXAMPLES_BY_TYPE,
    _STANDARD_SELECTION_COMMON_EXAMPLES,
    STANDARD_SELECTION_USER,
    FIELD_NAME_REWRITE_SYSTEM,
    FIELD_NAME_REWRITE_USER,
    FIELD_NAME_DATETIME_REWRITE_SYSTEM,
    FIELD_NAME_DATETIME_REWRITE_USER,
)


def _build_standard_selection_system(field_type: str) -> str:
    """按字段所属类型组装标准选择 system prompt。

    Args:
        field_type: 字段所属类型（编码类/文本类/数值类/日期时间类/标志类/代码枚举类等）。
                    未覆盖的类型回退到"编码类"示例。

    Returns:
        组装后的 system prompt 文本
    """
    examples = _STANDARD_SELECTION_COMMON_EXAMPLES + "\n" + STANDARD_SELECTION_EXAMPLES_BY_TYPE.get(
        field_type, STANDARD_SELECTION_EXAMPLES_BY_TYPE["编码类"]
    )
    return STANDARD_SELECTION_COMMON.format(examples=examples)


# ============================================================
# 标准选择
# ============================================================

def select_standard_batch(
    llm: ChatOpenAI,
    rows: list[dict],
    field_type: str,
    log_module: str = "standard_mapping",
) -> StandardSelectionResult:
    """调用 LLM 批量选择最合适的标准。

    Args:
        llm: LLM 实例
        rows: [{"row_index": 0, "field_name": "...", "field_type": "...",
                "business_meaning": "...", "data_example": "...",
                "candidates": [...]}, ...]
        field_type: 字段所属类型（用于组装对应类型的 system prompt）
        log_module: 日志目录名（enum_standard_mapping 复用本函数时传入）

    Returns:
        StandardSelectionResult
    """
    data_str = json.dumps(rows, ensure_ascii=False, indent=2)
    user_text = STANDARD_SELECTION_USER.format(data=data_str)
    return call_with_retry(
        llm, StandardSelectionResult, _build_standard_selection_system(field_type), user_text,
        module=log_module, label="标准选择",
    )


def select_standard(
    llm: ChatOpenAI,
    rows_data: list[dict],
    log_module: str = "standard_mapping",
) -> list[dict]:
    """分批调用 LLM 选择标准，返回扁平结果列表。

    Args:
        llm: LLM 实例
        rows_data: [{"row_index": 0, "field_name": "...", "field_type": "...",
                     "candidates": [...]}, ...]
        log_module: 日志目录名（enum_standard_mapping 复用本函数时传入）

    Returns:
        [{"row_index": 0, "selection": "复用已有标准",
           "selected_std_id": "...", "selected_std_name": "...",
           "extension_suggestion": "...", "reasoning": "..."}, ...]
    """
    all_results = []

    # 按字段所属类型分组，每组使用对应类型的 system prompt（当前各类型示例一致）
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows_data:
        groups[r.get("field_type") or ""].append(r)

    for field_type, group_rows in groups.items():
        total = len(group_rows)
        for i, batch in enumerate(chunked(group_rows, BATCH_SIZE)):
            print(f"  [标准选择] 类型[{field_type or '未知'}] 批次 {i + 1}/"
                  f"{(total + BATCH_SIZE - 1) // BATCH_SIZE}，处理 {len(batch)} 行...")
            result = select_standard_batch(llm, batch, field_type, log_module=log_module)
            for item in result.results:
                all_results.append({
                    "row_index": item.row_index,
                    "selection": item.selection,
                    "selected_std_id": item.selected_std_id,
                    "selected_std_name": item.selected_std_name,
                    "extension_suggestion": item.extension_suggestion,
                    "reasoning": item.reasoning,
                })

    return all_results


# ============================================================
# 字段名改写（标志类 + 枚举值非"是/否"时，检索前预处理）
# ============================================================

def rewrite_field_names_batch(
    llm: ChatOpenAI,
    rows: list[dict],
    log_module: str = "standard_mapping",
) -> FieldNameRewriteResult:
    """调用 LLM 批量改写字段名。

    Args:
        llm: LLM 实例
        rows: [{"row_index": 0, "field_name": "...", "business_meaning": "...",
                "enum_values": "...", "data_example": "..."}, ...]
        log_module: 日志目录名

    Returns:
        FieldNameRewriteResult
    """
    data_str = json.dumps(rows, ensure_ascii=False, indent=2)
    user_text = FIELD_NAME_REWRITE_USER.format(data=data_str)
    return call_with_retry(
        llm, FieldNameRewriteResult, FIELD_NAME_REWRITE_SYSTEM, user_text,
        module=log_module, label="字段名改写",
    )


def rewrite_field_names(
    llm: ChatOpenAI,
    rows_data: list[dict],
    log_module: str = "standard_mapping",
) -> list[dict]:
    """分批调用 LLM 改写字段名，返回扁平结果列表。

    Args:
        llm: LLM 实例
        rows_data: [{"row_index": 0, "field_name": "...", "business_meaning": "...",
                     "enum_values": "...", "data_example": "..."}, ...]
        log_module: 日志目录名

    Returns:
        [{"row_index": 0, "rewritten_field_name": "...",
          "rewritten_business_meaning": "...", "reasoning": "..."}, ...]
    """
    all_results = []
    total = len(rows_data)

    for i, batch in enumerate(chunked(rows_data, BATCH_SIZE)):
        print(f"  [字段名改写] 批次 {i + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE}，"
              f"处理 {len(batch)} 行...")
        result = rewrite_field_names_batch(llm, batch, log_module=log_module)
        for item in result.results:
            all_results.append({
                "row_index": item.row_index,
                "rewritten_field_name": item.rewritten_field_name,
                "rewritten_business_meaning": item.rewritten_business_meaning,
                "reasoning": item.reasoning,
            })

    return all_results


# ============================================================
# 日期时间字段名改写（日期时间类字段，检索前预处理）
# ============================================================

def rewrite_datetime_field_names_batch(
    llm: ChatOpenAI,
    rows: list[dict],
    log_module: str = "standard_mapping",
) -> FieldNameRewriteResult:
    """调用 LLM 批量改写日期时间类字段的字段名。

    Args:
        llm: LLM 实例
        rows: [{"row_index": 0, "field_name": "...", "business_meaning": "...",
                "data_example": "...", "detected_type": "日期/时间/时间戳"}, ...]
        log_module: 日志目录名

    Returns:
        FieldNameRewriteResult
    """
    data_str = json.dumps(rows, ensure_ascii=False, indent=2)
    user_text = FIELD_NAME_DATETIME_REWRITE_USER.format(data=data_str)
    return call_with_retry(
        llm, FieldNameRewriteResult, FIELD_NAME_DATETIME_REWRITE_SYSTEM, user_text,
        module=log_module, label="日期时间字段名改写",
    )


def rewrite_datetime_field_names(
    llm: ChatOpenAI,
    rows_data: list[dict],
    log_module: str = "standard_mapping",
) -> list[dict]:
    """分批调用 LLM 改写日期时间类字段的字段名，返回扁平结果列表。

    Args:
        llm: LLM 实例
        rows_data: [{"row_index": 0, "field_name": "...", "business_meaning": "...",
                     "data_example": "...", "detected_type": "日期/时间/时间戳"}, ...]
        log_module: 日志目录名

    Returns:
        [{"row_index": 0, "rewritten_field_name": "...",
          "rewritten_business_meaning": "...", "reasoning": "..."}, ...]
    """
    all_results = []
    total = len(rows_data)

    for i, batch in enumerate(chunked(rows_data, BATCH_SIZE)):
        print(f"  [日期时间字段名改写] 批次 {i + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE}，"
              f"处理 {len(batch)} 行...")
        result = rewrite_datetime_field_names_batch(llm, batch, log_module=log_module)
        for item in result.results:
            all_results.append({
                "row_index": item.row_index,
                "rewritten_field_name": item.rewritten_field_name,
                "rewritten_business_meaning": item.rewritten_business_meaning,
                "reasoning": item.reasoning,
            })

    return all_results
