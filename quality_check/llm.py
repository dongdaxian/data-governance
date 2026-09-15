"""数据质量检查 -- 模块专用 LLM 调用。

包含业务含义检查和枚举值规范化的 LLM 调用逻辑。
"""

import concurrent.futures
import json
from concurrent.futures import ThreadPoolExecutor

from config import BATCH_SIZE

from langchain_openai import ChatOpenAI

from common.llm_client import get_llm, call_with_retry, chunked
from quality_check.state import (
    BusinessMeaningResult,
    EnumNormalizationResult,
    FieldTypeCheckResult,
    EnumAntonymResult,
    DataExampleCheckResult,
)
from quality_check.prompts import (
    BUSINESS_MEANING_SYSTEM,
    BUSINESS_MEANING_USER,
    ENUM_NORMALIZATION_SYSTEM,
    ENUM_NORMALIZATION_USER,
    FIELD_TYPE_CHECK_SYSTEM,
    FIELD_TYPE_CHECK_USER,
    ENUM_ANTONYM_SYSTEM,
    ENUM_ANTONYM_USER,
    DATA_EXAMPLE_CHECK_SYSTEM,
    DATA_EXAMPLE_CHECK_USER,
)


# 并发批次数：LLM 调用为 IO 密集，线程并发可显著提速（受 API 并发限制约束）
LLM_CONCURRENCY = 4


def _run_batches_parallel(fn, llm: ChatOpenAI, rows_data: list[dict], label: str):
    """并发执行各批次 LLM 调用，按批次顺序返回 [(批次号, result), ...]。

    Args:
        fn: 单批次调用函数（接收 llm 和一批数据，返回结构化结果）
        llm: LLM 实例
        rows_data: 待处理数据行
        label: 打印用标签（如"业务含义检查"）

    Returns:
        按批次号升序的 [(idx, result), ...]
    """
    batches = list(chunked(rows_data, BATCH_SIZE))
    total = len(batches)

    def worker(idx_batch):
        idx, batch = idx_batch
        print(f"  [{label}] 批次 {idx + 1}/{total}，处理 {len(batch)} 行...")
        result = fn(llm, batch)
        return idx, result

    ordered = []
    with ThreadPoolExecutor(max_workers=LLM_CONCURRENCY) as ex:
        futures = [ex.submit(worker, (i, b)) for i, b in enumerate(batches)]
        for fut in concurrent.futures.as_completed(futures):
            ordered.append(fut.result())
    ordered.sort(key=lambda x: x[0])
    return ordered


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
    """分批并发调用 LLM 检查业务含义，返回扁平结果列表。

    Args:
        llm: LLM 实例
        rows_data: [{"row_index": 0, "字段中文名": "...", "业务含义": "..."}, ...]

    Returns:
        [{"row_index": 0, "is_meaningful": True, "reason": "..."}, ...]
    """
    all_results = []

    for _, result in _run_batches_parallel(
        check_business_meaning_batch, llm, rows_data, "业务含义检查"
    ):
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
    """分批并发调用 LLM 规范化枚举值，返回扁平结果列表。

    Args:
        llm: LLM 实例
        rows_data: [{"row_index": 0, "枚举值": "..."}, ...]

    Returns:
        [{"row_index": 0, "normalized": "...", "needs_normalization": True}, ...]
    """
    all_results = []

    for _, result in _run_batches_parallel(
        normalize_enum_batch, llm, rows_data, "枚举值规范化"
    ):
        for item in result.results:
            all_results.append({
                "row_index": item.row_index,
                "normalized": item.normalized,
                "needs_normalization": item.needs_normalization,
                "has_codes": item.has_codes,
            })

    return all_results


# ============================================================
# 字段所属类型检查
# ============================================================

def check_field_type_batch(
    llm: ChatOpenAI,
    rows: list[dict],
) -> FieldTypeCheckResult:
    """调用 LLM 批量检查字段所属类型是否正确。

    Args:
        llm: LLM 实例
        rows: [{"row_index": 0, "中文字段名": "...", "业务定义": "...", "字段所属类型": "..."}, ...]

    Returns:
        FieldTypeCheckResult
    """
    data_str = json.dumps(rows, ensure_ascii=False, indent=2)
    user_text = FIELD_TYPE_CHECK_USER.format(data=data_str)
    return call_with_retry(llm, FieldTypeCheckResult, FIELD_TYPE_CHECK_SYSTEM, user_text)


def check_field_types(
    llm: ChatOpenAI,
    rows_data: list[dict],
) -> list[dict]:
    """分批并发调用 LLM 检查字段所属类型，返回扁平结果列表。

    Args:
        llm: LLM 实例
        rows_data: [{"row_index": 0, "中文字段名": "...", "业务定义": "...", "字段所属类型": "..."}, ...]

    Returns:
        [{"row_index": 0, "is_correct": True, "correct_type": "", "reason": "..."}, ...]
    """
    all_results = []

    for _, result in _run_batches_parallel(
        check_field_type_batch, llm, rows_data, "所属类型检查"
    ):
        for item in result.results:
            all_results.append({
                "row_index": item.row_index,
                "is_correct": item.is_correct,
                "correct_type": item.correct_type,
                "reason": item.reason,
            })

    return all_results


# ============================================================
# 枚举值反义词判断
# ============================================================

def check_enum_antonym_batch(
    llm: ChatOpenAI,
    rows: list[dict],
) -> EnumAntonymResult:
    """调用 LLM 批量判断枚举值两项码值是否反义词。

    Args:
        llm: LLM 实例
        rows: [{"row_index": 0, "字段中文名": "...", "枚举值": "01-通过;02-不通过"}, ...]

    Returns:
        EnumAntonymResult
    """
    data_str = json.dumps(rows, ensure_ascii=False, indent=2)
    user_text = ENUM_ANTONYM_USER.format(data=data_str)
    return call_with_retry(llm, EnumAntonymResult, ENUM_ANTONYM_SYSTEM, user_text)


def check_enum_antonyms(
    llm: ChatOpenAI,
    rows_data: list[dict],
) -> list[dict]:
    """并发分批调用 LLM 判断枚举值反义词，返回扁平结果列表。

    Args:
        llm: LLM 实例
        rows_data: [{"row_index": 0, "字段中文名": "...", "枚举值": "..."}, ...]

    Returns:
        [{"row_index": 0, "is_antonym": True, "reason": "..."}, ...]
    """
    all_results = []

    for _, result in _run_batches_parallel(
        check_enum_antonym_batch, llm, rows_data, "枚举反义词检查"
    ):
        for item in result.results:
            all_results.append({
                "row_index": item.row_index,
                "is_antonym": item.is_antonym,
                "reason": item.reason,
            })

    return all_results


# ============================================================
# 数据示例语义检查
# ============================================================

def check_data_example_batch(
    llm: ChatOpenAI,
    rows: list[dict],
) -> DataExampleCheckResult:
    """调用 LLM 批量检查数据示例语义风险。

    Args:
        llm: LLM 实例
        rows: 数据示例检查输入列表

    Returns:
        DataExampleCheckResult
    """
    data_str = json.dumps(rows, ensure_ascii=False, indent=2)
    user_text = DATA_EXAMPLE_CHECK_USER.format(data=data_str)
    return call_with_retry(llm, DataExampleCheckResult, DATA_EXAMPLE_CHECK_SYSTEM, user_text)


def check_data_examples(
    llm: ChatOpenAI,
    rows_data: list[dict],
) -> list[dict]:
    """分批并发调用 LLM 检查数据示例，返回扁平结果列表。

    Args:
        llm: LLM 实例
        rows_data: [{"row_index": 0, "字段中文名": "...", ...}, ...]

    Returns:
        [{"row_index": 0, "has_real_meaning": True, ...}, ...]
    """
    all_results = []

    for _, result in _run_batches_parallel(
        check_data_example_batch, llm, rows_data, "数据示例语义检查"
    ):
        for item in result.results:
            all_results.append({
                "row_index": item.row_index,
                "has_real_meaning": item.has_real_meaning,
                "is_name_consistent": item.is_name_consistent,
                "is_type_consistent": item.is_type_consistent,
                "suggested_field_type": item.suggested_field_type,
                "reason": item.reason,
            })

    return all_results
