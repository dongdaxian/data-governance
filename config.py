"""配置文件 -- LLM API Key、模型参数等全局配置。

使用方式：
  1. 直接修改下方 ZHIPUAI_API_KEY 的值
  2. 或者在项目根目录创建 .env 文件，写入 ZHIPUAI_API_KEY=你的key
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ============================================================
# LLM 配置
# ============================================================

# 智谱AI API Key -- 请在此处填写你的 key
ZHIPUAI_API_KEY = os.getenv("ZHIPUAI_API_KEY", "YOUR_API_KEY_HERE")

# 智谱AI OpenAI兼容接口地址
ZHIPUAI_BASE_URL = os.getenv("ZHIPUAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")

# 模型名称（glm-5.2 于 2026-06-16 上线）
LLM_MODEL = os.getenv("LLM_MODEL", "glm-5.2")

# LLM 生成参数
LLM_TEMPERATURE = 0.1  # 低温度确保判断结果稳定一致
LLM_MAX_TOKENS = 4096

# 批处理大小：每次 LLM 调用处理的行数
BATCH_SIZE = 20

# LLM 调用失败时的最大重试次数
MAX_RETRIES = 3
