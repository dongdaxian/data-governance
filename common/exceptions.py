# -*- coding: utf-8 -*-
"""项目统一异常分类体系。

判断标准：这个错误 10 秒后原样重试一次，有没有可能成功？
- 有可能（网络超时、连接中断、限流）→ RetryableError
- 不可能（鉴权失败、配置错误、schema 不匹配）→ NonRetryableError
"""


class GovernanceError(Exception):
    """项目统一异常基类。"""


class RetryableError(GovernanceError):
    """瞬时性错误，值得重试：网络超时、连接中断、限流等。"""


class NonRetryableError(GovernanceError):
    """确定性错误，重试无意义：鉴权失败、配置错误、schema 不匹配、参数非法。"""


# ============================================================
# Milvus 异常
# ============================================================


class MilvusConnectionError(RetryableError):
    """Milvus 连接/网络类错误（超时、断连、服务不可用）。"""


class MilvusAuthError(NonRetryableError):
    """Milvus 鉴权失败（如 MILVUS_TOKEN 错误）。"""


class MilvusSchemaError(NonRetryableError):
    """Milvus schema 不匹配（集合/字段/维度不符）。"""


# ============================================================
# LLM 异常
# ============================================================


class LLMAuthError(NonRetryableError):
    """LLM API Key 无效或过期。"""


class LLMRateLimitError(RetryableError):
    """LLM 触发限流（429）。"""


class LLMTimeoutError(RetryableError):
    """LLM 网络超时/连接错误。"""


class LLMResponseFormatError(RetryableError):
    """LLM 返回格式异常（结构化输出解析失败/function call 未触发）。

    归为可重试：格式抖动是模型瞬态行为，快速重试通常可恢复，
    与 llm_client 既有"格式错误 1s 快速重试"逻辑一致。
    """
