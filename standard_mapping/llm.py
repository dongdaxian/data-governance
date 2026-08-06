"""落标处理 -- 模块专用 LLM 调用。

包含标准选择的 LLM 调用逻辑。
"""

import json

from langchain_openai import ChatOpenAI

from common.llm_client import get_llm, call_with_retry, chunked
from config import BATCH_SIZE
from standard_mapping.state import StandardSelectionResult
from standard_mapping.prompts import (
    STANDARD_SELECTION_SYSTEM,
    STANDARD_SELECTION_USER,
)


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
