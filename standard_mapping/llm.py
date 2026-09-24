"""落标处理 -- 模块专用 LLM 调用。

包含标准选择的 LLM 调用逻辑。
"""

import json

from config import BATCH_SIZE

from langchain_openai import ChatOpenAI

from common.llm_client import get_llm, call_with_retry, chunked
from standard_mapping.state import (
    StandardSelectionResult,
    FieldNameRewriteResult,
)
from standard_mapping.prompts import (
    STANDARD_SELECTION_SYSTEM,
    STANDARD_SELECTION_USER,
    FIELD_NAME_REWRITE_SYSTEM,
    FIELD_NAME_REWRITE_USER,
)


# ============================================================
# 标准选择
# ============================================================

def select_standard_batch(
    llm: ChatOpenAI,
    rows: list[dict],
    log_module: str = "standard_mapping",
) -> StandardSelectionResult:
    """调用 LLM 批量选择最合适的标准。

    Args:
        llm: LLM 实例
        rows: [{"row_index": 0, "field_name": "...", "field_type": "...",
                "business_meaning": "...", "data_example": "...",
                "candidates": [...]}, ...]
        log_module: 日志目录名（enum_standard_mapping 复用本函数时传入）

    Returns:
        StandardSelectionResult
    """
    data_str = json.dumps(rows, ensure_ascii=False, indent=2)
    user_text = STANDARD_SELECTION_USER.format(data=data_str)
    return call_with_retry(
        llm, StandardSelectionResult, STANDARD_SELECTION_SYSTEM, user_text,
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
        rows_data: [{"row_index": 0, "field_name": "...", "candidates": [...]}, ...]
        log_module: 日志目录名（enum_standard_mapping 复用本函数时传入）

    Returns:
        [{"row_index": 0, "selection": "复用已有标准",
           "selected_std_id": "...", "selected_std_name": "...",
           "extension_suggestion": "...", "reasoning": "..."}, ...]
    """
    all_results = []
    total = len(rows_data)

    for i, batch in enumerate(chunked(rows_data, BATCH_SIZE)):
        print(f"  [标准选择] 批次 {i + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE}，"
              f"处理 {len(batch)} 行...")
        result = select_standard_batch(llm, batch, log_module=log_module)
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
