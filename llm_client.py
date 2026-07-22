"""LLM 客户端封装 -- 使用 LangChain ChatOpenAI 接入智谱AI GLM-5.2。

通过 with_structured_output 实现 Pydantic Schema 约束的结构化输出，
内置重试机制应对偶发的 API 超时或格式异常。
"""

import json
import time

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

from config import (
    ZHIPUAI_API_KEY,
    ZHIPUAI_BASE_URL,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
    BATCH_SIZE,
    MAX_RETRIES,
)
from state import (
    BusinessMeaningResult,
    EnumNormalizationResult,
)
from prompts import (
    BUSINESS_MEANING_SYSTEM,
    BUSINESS_MEANING_USER,
    ENUM_NORMALIZATION_SYSTEM,
    ENUM_NORMALIZATION_USER,
)


def get_llm() -> ChatOpenAI:
    """创建 LLM 实例。"""
    if ZHIPUAI_API_KEY == "YOUR_API_KEY_HERE":
        raise ValueError(
            "请先配置 API Key！\n"
            "  方式1：在 config.py 中修改 ZHIPUAI_API_KEY\n"
            "  方式2：在项目根目录创建 .env 文件，写入 ZHIPUAI_API_KEY=你的key"
        )
    return ChatOpenAI(
        model=LLM_MODEL,
        api_key=ZHIPUAI_API_KEY,
        base_url=ZHIPUAI_BASE_URL,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
    )


def _call_with_retry(llm: ChatOpenAI, schema, system_text: str, user_text: str):
    """带重试的结构化输出调用。"""
    structured_llm = llm.with_structured_output(schema)
    messages = [SystemMessage(content=system_text), HumanMessage(content=user_text)]

    for attempt in range(MAX_RETRIES):
        try:
            result = structured_llm.invoke(messages)
            return result
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise RuntimeError(f"LLM 调用失败（重试{MAX_RETRIES}次后仍报错）: {e}") from e
            wait = 2 ** attempt
            print(f"  [重试 {attempt + 1}/{MAX_RETRIES}] {wait}秒后重试... 错误: {e}")
            time.sleep(wait)


def _chunked(items: list, size: int):
    """将列表分块。"""
    for i in range(0, len(items), size):
        yield items[i : i + size]


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
    return _call_with_retry(llm, BusinessMeaningResult, BUSINESS_MEANING_SYSTEM, user_text)


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

    for i, batch in enumerate(_chunked(rows_data, BATCH_SIZE)):
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
    return _call_with_retry(llm, EnumNormalizationResult, ENUM_NORMALIZATION_SYSTEM, user_text)


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

    for i, batch in enumerate(_chunked(rows_data, BATCH_SIZE)):
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
