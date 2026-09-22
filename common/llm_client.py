"""LLM 客户端通用封装 -- 使用 LangChain ChatOpenAI 接入火山引擎 GLM-5.2。

通过 with_structured_output 实现 Pydantic Schema 约束的结构化输出，
内置重试机制应对偶发的 API 超时或格式异常。
"""

import datetime
import json
import os
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


# ============================================================
# LLM 调用日志（logs/<模块>/<模块>_<时间戳>.txt）
# ============================================================

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_ROOT = os.path.join(PROJECT_ROOT, "logs")

# 进程内按模块缓存日志文件路径：一个模块一次运行只生成一个文件
_log_paths: dict[str, str] = {}


def _get_log_path(module: str) -> str:
    """按模块生成日志文件路径（首次调用时创建，文件名含程序开始时间戳）。"""
    if module not in _log_paths:
        sub = os.path.join(LOG_ROOT, module)
        os.makedirs(sub, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(sub, f"{module}_{ts}.txt")
        n = 2
        while os.path.exists(path):
            path = os.path.join(sub, f"{module}_{ts}_{n}.txt")
            n += 1
        _log_paths[module] = path
    return _log_paths[module]


def _append_log(module: str, text: str) -> None:
    """向模块日志文件追加内容；失败仅打印警告，不影响主流程。"""
    try:
        path = _get_log_path(module)
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        print(f"  [WARNING] 写入 LLM 日志失败: {e}")


def append_module_log(module: str, text: str) -> None:
    """向模块日志文件追加内容（供非 LLM 调用方复用同一模块日志文件）。"""
    _append_log(module, text)


def _result_to_json(result) -> str:
    """将 LLM 结构化结果序列化为便于阅读的 JSON 字符串。"""
    if hasattr(result, "model_dump_json"):
        return result.model_dump_json(indent=2, ensure_ascii=False)
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False, indent=2)
    return str(result)


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


def call_with_retry(
    llm: ChatOpenAI,
    schema,
    system_text: str,
    user_text: str,
    module: str = "general",
    label: str = "",
):
    """带重试的结构化输出调用，并把每次输入/输出追加到 logs/<module>/ 下的 txt 日志。"""
    structured_llm = llm.with_structured_output(schema, method="function_calling")
    messages = [SystemMessage(content=system_text), HumanMessage(content=user_text)]

    model_name = getattr(llm, "model_name", None) or LLM_MODEL

    for attempt in range(MAX_RETRIES):
        print(f"  [LLM 调用] 第 {attempt + 1}/{MAX_RETRIES} 次尝试")
        print(f"  [LLM 调用] system({len(system_text)}字): {system_text}")
        print(f"  [LLM 调用] user({len(user_text)}字): {user_text}")
        _append_log(
            module,
            "\n" + "=" * 60
            + f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            + f"模块: {module} | 调用: {label or '-'} | 模型: {model_name} | 第 {attempt + 1}/{MAX_RETRIES} 次尝试"
            + f"\n--- system ---\n{system_text}"
            + f"\n--- user ---\n{user_text}\n",
        )
        start = time.perf_counter()
        try:
            result = structured_llm.invoke(messages)
            elapsed = time.perf_counter() - start
            print(f"  [LLM 调用] 耗时 {elapsed:.1f}秒，返回: {result}")
            if result is None:
                raise ValueError("LLM returned None (function call not invoked)")
            _append_log(
                module,
                f"--- result ---\n{_result_to_json(result)}\n"
                f"耗时 {elapsed:.1f}秒\n",
            )
            return result
        except Exception as e:
            elapsed = time.perf_counter() - start
            translated = translate_llm_error(e)
            # 鉴权/配置类错误重试无意义，立刻向上抛
            if isinstance(translated, LLMAuthError):
                _append_log(module, f"--- error ---\n{e}\n")
                raise translated from e
            if attempt == MAX_RETRIES - 1:
                _append_log(module, f"--- error ---\n{e}\n")
                raise RuntimeError(f"LLM 调用失败（重试{MAX_RETRIES}次后仍报错）: {e}") from e
            # 格式抖动（function call 未触发等）短间隔快速重试；
            # 网络/限流等异常按指数退避
            is_format_error = isinstance(translated, LLMResponseFormatError)
            wait = 1 if is_format_error else 2 ** attempt
            print(f"  [重试 {attempt + 1}/{MAX_RETRIES}] 本次耗时 {elapsed:.1f}秒，{wait}秒后重试... 错误: {e}")
            _append_log(
                module,
                f"--- error (本次耗时 {elapsed:.1f}秒) ---\n{e}\n{wait}秒后重试\n",
            )
            time.sleep(wait)


def chunked(items: list, size: int):
    """将列表分块。"""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def build_row_result_map(results: list[dict]) -> tuple[dict, set]:
    """按 row_index 建立 LLM 结果索引，并识别重复返回的行号。"""
    result_map = {}
    duplicate_indices = set()
    for result in results:
        row_index = result["row_index"]
        if row_index in result_map:
            duplicate_indices.add(row_index)
        result_map[row_index] = result
    return result_map, duplicate_indices
