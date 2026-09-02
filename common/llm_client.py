"""LLM 客户端通用封装 -- 使用 LangChain ChatOpenAI 接入火山引擎 GLM-5.2。

通过 with_structured_output 实现 Pydantic Schema 约束的结构化输出，
内置重试机制应对偶发的 API 超时或格式异常。
"""

import time

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

from config import (
    API_KEY,
    BASE_URL,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
    MAX_RETRIES,
)


def get_llm() -> ChatOpenAI:
    """创建 LLM 实例。"""
    return ChatOpenAI(
        model=LLM_MODEL,
        api_key=API_KEY,
        base_url=BASE_URL,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
    )


def call_with_retry(llm: ChatOpenAI, schema, system_text: str, user_text: str):
    """带重试的结构化输出调用。"""
    structured_llm = llm.with_structured_output(schema, method="function_calling")
    messages = [SystemMessage(content=system_text), HumanMessage(content=user_text)]

    for attempt in range(MAX_RETRIES):
        print(f"  [LLM 调用] 第 {attempt + 1}/{MAX_RETRIES} 次尝试")
        print(f"  [LLM 调用] system({len(system_text)}字): {system_text}")
        print(f"  [LLM 调用] user({len(user_text)}字): {user_text}")
        start = time.perf_counter()
        try:
            result = structured_llm.invoke(messages)
            elapsed = time.perf_counter() - start
            print(f"  [LLM 调用] 耗时 {elapsed:.1f}秒，返回: {result}")
            if result is None:
                raise ValueError("LLM returned None (function call not invoked)")
            return result
        except Exception as e:
            elapsed = time.perf_counter() - start
            if attempt == MAX_RETRIES - 1:
                raise RuntimeError(f"LLM 调用失败（重试{MAX_RETRIES}次后仍报错）: {e}") from e
            # None（未触发 function call）是模型格式抖动，短间隔快速重试；
            # 网络/限流等异常按指数退避
            is_format_error = isinstance(e, ValueError)
            wait = 1 if is_format_error else 2 ** attempt
            print(f"  [重试 {attempt + 1}/{MAX_RETRIES}] 本次耗时 {elapsed:.1f}秒，{wait}秒后重试... 错误: {e}")
            time.sleep(wait)


def chunked(items: list, size: int):
    """将列表分块。"""
    for i in range(0, len(items), size):
        yield items[i : i + size]
