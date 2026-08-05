"""落标处理 -- 模块专用 LLM 调用。

包含域类型冲突检测和标准选择的 LLM 调用逻辑。
"""

import json

from langchain_openai import ChatOpenAI

from common.llm_client import get_llm, call_with_retry, chunked
from config import BATCH_SIZE
from standard_mapping.state import (
    DomainCheckResult,
    StandardSelectionResult,
)
from standard_mapping.prompts import (
    DOMAIN_CHECK_SYSTEM,
    DOMAIN_CHECK_USER,
    STANDARD_SELECTION_SYSTEM,
    STANDARD_SELECTION_USER,
)


# ============================================================
# 域类型冲突检测
# ============================================================

def check_domain_conflict_batch(
    llm: ChatOpenAI,
    rows: list[dict],
) -> DomainCheckResult:
    """调用 LLM 批量检测域类型冲突并寻找替代域。

    Args:
        llm: LLM 实例
        rows: [{"row_index": 0, "candidate_index": 0, "field_name": "...",
                "data_example": "...", "current_domain_type": "...",
                "available_domains": [...]}, ...]

    Returns:
        DomainCheckResult
    """
    data_str = json.dumps(rows, ensure_ascii=False, indent=2)
    user_text = DOMAIN_CHECK_USER.format(data=data_str)
    return call_with_retry(llm, DomainCheckResult, DOMAIN_CHECK_SYSTEM, user_text)


def check_domain_conflict(
    llm: ChatOpenAI,
    rows_data: list[dict],
) -> list[dict]:
    """分批调用 LLM 检测域类型冲突，返回扁平结果列表。

    Args:
        llm: LLM 实例
        rows_data: [{"row_index": 0, "candidate_index": 0, ...}, ...]

    Returns:
        [{"row_index": 0, "candidate_index": 0, "has_conflict": True,
           "needs_domain_change": True, "new_domain_id": "...",
           "new_domain_name": "...", "new_domain_type": "...",
           "reason": "..."}, ...]
    """
    all_results = []
    total = len(rows_data)

    for i, batch in enumerate(chunked(rows_data, BATCH_SIZE)):
        print(f"  [域类型冲突检测] 批次 {i + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE}，"
              f"处理 {len(batch)} 条...")
        result = check_domain_conflict_batch(llm, batch)
        for item in result.results:
            all_results.append({
                "row_index": item.row_index,
                "candidate_index": item.candidate_index,
                "has_conflict": item.has_conflict,
                "needs_domain_change": item.needs_domain_change,
                "new_domain_id": item.new_domain_id,
                "new_domain_name": item.new_domain_name,
                "new_domain_type": item.new_domain_type,
                "reason": item.reason,
            })

    return all_results


# ============================================================
# 标准选择
# ============================================================

def select_standard_batch(
    llm: ChatOpenAI,
    rows: list[dict],
) -> StandardSelectionResult:
    """调用 LLM 批量选择最合适的标准。

    Args:
        llm: LLM 实例
        rows: [{"row_index": 0, "field_name": "...", "field_type": "...",
                "business_meaning": "...", "data_example": "...",
                "candidates": [...]}, ...]

    Returns:
        StandardSelectionResult
    """
    data_str = json.dumps(rows, ensure_ascii=False, indent=2)
    user_text = STANDARD_SELECTION_USER.format(data=data_str)
    return call_with_retry(llm, StandardSelectionResult, STANDARD_SELECTION_SYSTEM, user_text)


def select_standard(
    llm: ChatOpenAI,
    rows_data: list[dict],
) -> list[dict]:
    """分批调用 LLM 选择标准，返回扁平结果列表。

    Args:
        llm: LLM 实例
        rows_data: [{"row_index": 0, "field_name": "...", "candidates": [...]}, ...]

    Returns:
        [{"row_index": 0, "selection": "复用已有标准",
           "selected_std_id": "...", "selected_std_name": "...",
           "extension_suggestion": "...", "reason": "..."}, ...]
    """
    all_results = []
    total = len(rows_data)

    for i, batch in enumerate(chunked(rows_data, BATCH_SIZE)):
        print(f"  [标准选择] 批次 {i + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE}，"
              f"处理 {len(batch)} 行...")
        result = select_standard_batch(llm, batch)
        for item in result.results:
            all_results.append({
                "row_index": item.row_index,
                "selection": item.selection,
                "selected_std_id": item.selected_std_id,
                "selected_std_name": item.selected_std_name,
                "extension_suggestion": item.extension_suggestion,
                "reason": item.reason,
            })

    return all_results
