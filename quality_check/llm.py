"""数据质量检查 -- 模块专用 LLM 调用。

包含业务含义检查和枚举值规范化的 LLM 调用逻辑。
"""

import json

from langchain_openai import ChatOpenAI

from common.llm_client import get_llm, call_with_retry, chunked
from config import BATCH_SIZE
from quality_check.state import (
    BusinessMeaningResult,
    EnumNormalizationResult,
)
from quality_check.prompts import (
    BUSINESS_MEANING_SYSTEM,
    BUSINESS_MEANING_USER,
    ENUM_NORMALIZATION_SYSTEM,
    ENUM_NORMALIZATION_USER,
)


# ============================================================
# 业务含义检查
# ============================================================

def check_business_meaning_batch(
    llm: ChatOpenAI,
    rows: list[dict],
) -> BusinessMeaningResult:
    """调用 LLM 批量检查业务含义是否有效。

    Args:
        llm: LLM 实例
        rows: [{"row_index": 0, "字段中文名": "...", "业务含义": "..."}, ...]

    Returns:
        BusinessMeaningResult
    """
    data_str = json.dumps(rows, ensure_ascii=False, indent=2)
    user_text = BUSINESS_MEANING_USER.format(data=data_str)
    return call_with_retry(llm, BusinessMeaningResult, BUSINESS_MEANING_SYSTEM, user_text)


def check_business_meaning(
    llm: ChatOpenAI,
    rows_data: list[dict],
) -> list[dict]:
    """分批调用 LLM 检查业务含义，返回扁平结果列表。

    Args:
        llm: LLM 实例
        rows_data: [{"row_index": 0, "字段中文名": "...", "业务含义": "..."}, ...]

    Returns:
        [{"row_index": 0, "is_meaningful": True, "reason": "..."}, ...]
    """
    all_results = []
    total = len(rows_data)

    for i, batch in enumerate(chunked(rows_data, BATCH_SIZE)):
        print(f"  [业务含义检查] 批次 {i + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE}，"
              f"处理 {len(batch)} 行...")
        result = check_business_meaning_batch(llm, batch)
        for item in result.results:
            all_results.append({
                "row_index": item.row_index,
                "is_meaningful": item.is_meaningful,
                "reason": item.reason,
            })

    return all_results


# ============================================================
# 枚举值规范化
# ============================================================

def normalize_enum_batch(
    llm: ChatOpenAI,
    rows: list[dict],
) -> EnumNormalizationResult:
    """调用 LLM 批量规范化枚举值。

    Args:
        llm: LLM 实例
        rows: [{"row_index": 0, "枚举值": "..."}, ...]

    Returns:
        EnumNormalizationResult
    """
    data_str = json.dumps(rows, ensure_ascii=False, indent=2)
    user_text = ENUM_NORMALIZATION_USER.format(data=data_str)
    return call_with_retry(llm, EnumNormalizationResult, ENUM_NORMALIZATION_SYSTEM, user_text)


def normalize_enum_values(
    llm: ChatOpenAI,
    rows_data: list[dict],
) -> list[dict]:
    """分批调用 LLM 规范化枚举值，返回扁平结果列表。

    Args:
        llm: LLM 实例
        rows_data: [{"row_index": 0, "枚举值": "..."}, ...]

    Returns:
        [{"row_index": 0, "normalized": "...", "needs_normalization": True}, ...]
    """
    all_results = []
    total = len(rows_data)

    for i, batch in enumerate(chunked(rows_data, BATCH_SIZE)):
        print(f"  [枚举值规范化] 批次 {i + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE}，"
              f"处理 {len(batch)} 行...")
        result = normalize_enum_batch(llm, batch)
        for item in result.results:
            all_results.append({
                "row_index": item.row_index,
                "normalized": item.normalized,
                "needs_normalization": item.needs_normalization,
            })

    return all_results
