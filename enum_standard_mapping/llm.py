# -*- coding: utf-8 -*-
"""枚举落标处理 -- 模块专用 LLM 调用。"""

import json

from config import BATCH_SIZE

from langchain_openai import ChatOpenAI

from common.llm_client import call_with_retry, chunked
from enum_standard_mapping.state import EnumSelectionResult
from enum_standard_mapping.prompts import (
    ENUM_SELECTION_SYSTEM,
    ENUM_SELECTION_USER,
)


# ============================================================
# 七分类判定
# ============================================================

def select_enum_result_batch(
    llm: ChatOpenAI,
    rows: list[dict],
) -> EnumSelectionResult:
    """调用 LLM 批量判定七分类结果。"""
    data_str = json.dumps(rows, ensure_ascii=False, indent=2)
    user_text = ENUM_SELECTION_USER.format(data=data_str)
    return call_with_retry(llm, EnumSelectionResult, ENUM_SELECTION_SYSTEM, user_text)


def select_enum_result(
    llm: ChatOpenAI,
    rows_data: list[dict],
) -> list[dict]:
    """分批调用 LLM 判定七分类，返回扁平结果列表。"""
    all_results = []
    total = len(rows_data)

    for i, batch in enumerate(chunked(rows_data, BATCH_SIZE)):
        print(f"  [七分类判定] 批次 {i + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE}，"
              f"处理 {len(batch)} 行...")
        result = select_enum_result_batch(llm, batch)
        for item in result.results:
            all_results.append({
                "row_index": item.row_index,
                "selection": item.selection,
                "selected_std_id": item.selected_std_id,
                "selected_std_name": item.selected_std_name,
                "domain_action": item.domain_action,
                "conflict_detail": item.conflict_detail,
                "reason": item.reason,
            })

    return all_results
