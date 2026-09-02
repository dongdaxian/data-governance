"""配置文件 -- LLM API Key、模型参数等全局配置。



使用方式：

  1. 直接修改下方 API_KEY 的值

  2. 或者在项目根目录创建 .env 文件，写入 API_KEY=你的key

"""



import os

# 禁止 transformers 导入 TensorFlow（h5py 与 NumPy 2.x 二进制不兼容）
# 必须在所有可能触发 transformers 导入的模块之前设置
# huggingface_hub 会在 import 时缓存端点配置，HF 镜像相关环境变量同样必须提前设置
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")



from dotenv import load_dotenv



load_dotenv()



# ============================================================

# LLM 配置 -- 火山引擎 coding plan 

# ============================================================



# API Key（从 .env 文件读取，切勿硬编码在代码中）

API_KEY = os.getenv("API_KEY", "")



# OpenAI 兼容接口地址

BASE_URL = os.getenv("BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3")



# 模型名称

LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")



# LLM 生成参数

LLM_TEMPERATURE = 0.1  # 低温度确保判断结果稳定一致

LLM_MAX_TOKENS = 100000



# 批处理大小：每次 LLM 调用处理的行数

BATCH_SIZE = 10



# LLM 调用失败时的最大重试次数

MAX_RETRIES = 5





# ============================================================

# Milvus 向量库配置

# ============================================================



MILVUS_URI = os.getenv('MILVUS_URI', '')

MILVUS_TOKEN = os.getenv('MILVUS_TOKEN', '')

MILVUS_COLLECTION = os.getenv('MILVUS_COLLECTION', 'dict_non_enum')

# 按字段所属类型分 collection 存储，检索时只在对应类型的 collection 里搜
TYPE_COLLECTION_MAP = {
    "编码类": "dict_encode",
    "文本类": "dict_text",
    "数值类": "dict_number",
    "日期时间类": "dict_datetime",
    "标志类": "dict_flag",
}



# 代理配置：VPN/梯子场景下 gRPC 需要走 HTTP 代理隧道

# auto = 自动检测系统代理；none = 不使用代理；或直接填写代理地址

MILVUS_PROXY = os.getenv('MILVUS_PROXY', 'auto')



# 向量模型配置（bge-large-zh-v1.5）

EMBED_MODEL_NAME = os.getenv('EMBED_MODEL_NAME', 'BAAI/bge-large-zh-v1.5')

EMBED_DIMENSION = 1024

EMBED_QUERY_INSTRUCTION = '为这个句子生成表示以用于检索相关文章：'
# 向量化设备：cpu 或 cuda（有 GPU 时设为 cuda 可大幅加速）
EMBED_DEVICE = os.getenv('EMBED_DEVICE', 'cuda')


# 全量字典文件路径（用于候选标准信息回填）
DICTIONARY_PATH = os.path.join(os.path.dirname(__file__), 'data', 'dictionary_mock', '全量字典_最终.xlsx')


# ============================================================
# 枚举落标（enum_standard_mapping）配置
# ============================================================

# 枚举值码值向量集合名
ENUM_VALUE_COLLECTION = os.getenv('ENUM_VALUE_COLLECTION', 'dict_enum_values')

# 码值相似度阈值：单条码值向量检索相似度 >= 该值计为"命中"
ENUM_VALUE_MATCH_THRESHOLD = float(os.getenv('ENUM_VALUE_MATCH_THRESHOLD', '0.80'))

# 候选枚举值项数量：得分排序取前 N（含并列）
ENUM_CANDIDATE_TOP_N = int(os.getenv('ENUM_CANDIDATE_TOP_N', '20'))

# 每条码值检索返回条数（top_k，需覆盖同文本在多个枚举值项中的分布）
ENUM_VALUE_SEARCH_TOP_K = int(os.getenv('ENUM_VALUE_SEARCH_TOP_K', '300'))

# "大量重复"门槛：命中数/n >= 该值才触发补充类结果（4/5），如 0.67
ENUM_HEAVY_OVERLAP_RATIO = float(os.getenv('ENUM_HEAVY_OVERLAP_RATIO', '0.667'))

# 淘汰线：未命中数 >= ceil(n/2) 的枚举值项出局（代码内计算，无需配置）
