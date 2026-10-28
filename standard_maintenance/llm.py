# -*- coding: utf-8 -*-
"""标准维护 -- 模块专用 LLM 调用。

字段名规范化 / 业务定义生成 / 业务定义整合三个批量调用。
"""

import json

from config import STANDARD_MAPPING_BATCH_SIZE as BATCH_SIZE

from langchain_openai import ChatOpenAI

from common.llm_client import call_with_retry, chunked
from standard_maintenance.state import (
    NameNormalizeResult,
    DefinitionGenerateResult,
    DefinitionMergeResult,
)
from standard_maintenance.prompts import (
    NAME_NORMALIZE_SYSTEM,
    DEFINITION_GENERATE_SYSTEM,
    DEFINITION_MERGE_SYSTEM,
    STANDARD_USER,
)

LOG_MODULE = "standard_maintenance"


# ============================================================
# 步骤2：中文字段名规范化
# ============================================================

def normalize_field_names_batch(
    llm: ChatOpenAI,
    rows: list[dict],
) -> NameNormalizeResult:
    """调用 LLM 批量规范化中文字段名。

    Args:
        llm: LLM 实例
        rows: [{"row_index": 0, "field_name": "...", "business_meaning": "..."}, ...]

    Returns:
        NameNormalizeResult
    """
    data_str = json.dumps(rows, ensure_ascii=False, indent=2)
    user_text = STANDARD_USER.format(data=data_str)
    return call_with_retry(
        llm, NameNormalizeResult, NAME_NORMALIZE_SYSTEM, user_text,
        module=LOG_MODULE, label="字段名规范化",
    )


def normalize_field_names(
    llm: ChatOpenAI,
    rows_data: list[dict],
) -> list[dict]:
    """分批调用 LLM 规范化字段名，返回扁平结果列表。

    Returns:
        [{"row_index": 0, "normalized_name": "...", "changed": True,
          "reasoning": "..."}, ...]
    """
    all_results = []
    total = len(rows_data)

    for i, batch in enumerate(chunked(rows_data, BATCH_SIZE)):
        print(f"  [字段名规范化] 批次 {i + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE}，"
              f"处理 {len(batch)} 行...")
        result = normalize_field_names_batch(llm, batch)
        for item in result.results:
            all_results.append({
                "row_index": item.row_index,
                "normalized_name": item.normalized_name,
                "changed": item.changed,
                "reasoning": item.reasoning,
            })

    return all_results


# ============================================================
# 步骤3：业务定义生成
# ============================================================

def generate_definitions_batch(
    llm: ChatOpenAI,
    rows: list[dict],
) -> DefinitionGenerateResult:
    """调用 LLM 批量生成业务定义。

    Args:
        llm: LLM 实例
        rows: [{"row_index": 0, "field_name": "...", "field_type": "...",
                "enum_values": "...", "business_meaning": "..."}, ...]

    Returns:
        DefinitionGenerateResult
    """
    data_str = json.dumps(rows, ensure_ascii=False, indent=2)
    user_text = STANDARD_USER.format(data=data_str)
    return call_with_retry(
        llm, DefinitionGenerateResult, DEFINITION_GENERATE_SYSTEM, user_text,
        module=LOG_MODULE, label="业务定义生成",
    )


def generate_definitions(
    llm: ChatOpenAI,
    rows_data: list[dict],
) -> list[dict]:
    """分批调用 LLM 生成业务定义，返回扁平结果列表。

    Returns:
        [{"row_index": 0, "definition": "...", "reasoning": "..."}, ...]
    """
    all_results = []
    total = len(rows_data)

    for i, batch in enumerate(chunked(rows_data, BATCH_SIZE)):
        print(f"  [业务定义生成] 批次 {i + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE}，"
              f"处理 {len(batch)} 行...")
        result = generate_definitions_batch(llm, batch)
        for item in result.results:
            all_results.append({
                "row_index": item.row_index,
                "definition": item.definition,
                "reasoning": item.reasoning,
            })

    return all_results


# ============================================================
# 步骤4：业务定义对照整合
# ============================================================

def merge_definitions_batch(
    llm: ChatOpenAI,
    rows: list[dict],
) -> DefinitionMergeResult:
    """调用 LLM 批量对照整合业务定义。

    Args:
        llm: LLM 实例
        rows: [{"row_index": 0, "generated_definition": "...",
                "original_definition": "..."}, ...]

    Returns:
        DefinitionMergeResult
    """
    data_str = json.dumps(rows, ensure_ascii=False, indent=2)
    user_text = STANDARD_USER.format(data=data_str)
    return call_with_retry(
        llm, DefinitionMergeResult, DEFINITION_MERGE_SYSTEM, user_text,
        module=LOG_MODULE, label="业务定义整合",
    )


def merge_definitions(
    llm: ChatOpenAI,
    rows_data: list[dict],
) -> list[dict]:
    """分批调用 LLM 整合业务定义，返回扁平结果列表。

    Returns:
        [{"row_index": 0, "final_definition": "...", "merged": True,
          "reasoning": "..."}, ...]
    """
    all_results = []
    total = len(rows_data)

    for i, batch in enumerate(chunked(rows_data, BATCH_SIZE)):
        print(f"  [业务定义整合] 批次 {i + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE}，"
              f"处理 {len(batch)} 行...")
        result = merge_definitions_batch(llm, batch)
        for item in result.results:
            all_results.append({
                "row_index": item.row_index,
                "final_definition": item.final_definition,
                "merged": item.merged,
                "reasoning": item.reasoning,
            })

    return all_results
