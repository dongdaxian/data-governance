"""配置文件 -- LLM API Key、模型参数等全局配置。

使用方式：
  1. 直接修改下方 API_KEY 的值
  2. 或者在项目根目录创建 .env 文件，写入 API_KEY=你的key
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ============================================================
# LLM 配置 -- 火山引擎 coding plan (GLM-5.2)
# ============================================================

# API Key（从 .env 文件读取，切勿硬编码在代码中）
API_KEY = os.getenv("API_KEY", "")

# OpenAI 兼容接口地址
BASE_URL = os.getenv("BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3")

# 模型名称（glm-5.2）
LLM_MODEL = os.getenv("LLM_MODEL", "glm-5.2")

# LLM 生成参数
LLM_TEMPERATURE = 0.1  # 低温度确保判断结果稳定一致
LLM_MAX_TOKENS = 4096

# 批处理大小：每次 LLM 调用处理的行数
BATCH_SIZE = 20

# LLM 调用失败时的最大重试次数
MAX_RETRIES = 3


# ============================================================
# Milvus 向量库配置
# ============================================================

MILVUS_URI = os.getenv('MILVUS_URI', '')
MILVUS_TOKEN = os.getenv('MILVUS_TOKEN', '')
MILVUS_COLLECTION = os.getenv('MILVUS_COLLECTION', 'dict_non_enum')

# 代理配置：VPN/梯子场景下 gRPC 需要走 HTTP 代理隧道
# auto = 自动检测系统代理；none = 不使用代理；或直接填写代理地址
MILVUS_PROXY = os.getenv('MILVUS_PROXY', 'auto')

# 向量模型配置（bge-large-zh-v1.5）
EMBED_MODEL_NAME = os.getenv('EMBED_MODEL_NAME', 'BAAI/bge-large-zh-v1.5')
EMBED_DIMENSION = 1024
EMBED_QUERY_INSTRUCTION = '为这个句子生成表示以用于检索相关文章：'
# 向量化设备：cpu 或 cuda（有 GPU 时设为 cuda 可大幅加速）
EMBED_DEVICE = os.getenv('EMBED_DEVICE', 'cpu')

# 本地向量备份目录（Parquet 格式，Milvus 试用期 1 个月）
VECTOR_BACKUP_DIR = os.path.join(os.path.dirname(__file__), 'data', 'vector_backup')
