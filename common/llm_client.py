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

from common.exceptions import (
    LLMAuthError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMResponseFormatError,
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


def translate_llm_error(e: Exception):
    """将 LLM 原始异常翻译为分类异常。

    注意：LLMResponseFormatError 归为可重试——结构化输出偶发格式抖动
    （function call 未触发等）快速重试即可恢复，与原快速重试逻辑一致。
    """
    try:
        import openai
    except ImportError:
        openai = None

    if openai is not None:
        if isinstance(e, openai.AuthenticationError):
            return LLMAuthError(f"LLM API Key 无效或过期: {e}")
        if isinstance(e, openai.RateLimitError):
            return LLMRateLimitError(f"LLM 触发限流: {e}")
        if isinstance(e, (openai.APITimeoutError, openai.APIConnectionError)):
            return LLMTimeoutError(f"LLM 网络超时/连接错误: {e}")

    if isinstance(e, (ValueError, KeyError)):
        return LLMResponseFormatError(f"LLM 返回格式异常: {e}")

    return LLMTimeoutError(f"未分类 LLM 错误: {type(e).__name__}: {e}")


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
            translated = translate_llm_error(e)
            # 鉴权/配置类错误重试无意义，立刻向上抛
            if isinstance(translated, LLMAuthError):
                raise translated from e
            if attempt == MAX_RETRIES - 1:
                raise RuntimeError(f"LLM 调用失败（重试{MAX_RETRIES}次后仍报错）: {e}") from e
            # 格式抖动（function call 未触发等）短间隔快速重试；
            # 网络/限流等异常按指数退避
            is_format_error = isinstance(translated, LLMResponseFormatError)
            wait = 1 if is_format_error else 2 ** attempt
            print(f"  [重试 {attempt + 1}/{MAX_RETRIES}] 本次耗时 {elapsed:.1f}秒，{wait}秒后重试... 错误: {e}")
            time.sleep(wait)


def chunked(items: list, size: int):
    """将列表分块。"""
    for i in range(0, len(items), size):
        yield items[i : i + size]
