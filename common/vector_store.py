# -*- coding: utf-8 -*-

"""向量存储与检索模块 -- 基于 Milvus + bge-large-zh-v1.5 的稠密/稀疏混合检索。



核心功能：

  1. bge-large-zh-v1.5 文本向量化（CPU 推理，单例懒加载）

  2. Milvus 集合管理（创建 / 删除 / 加载）

  3. 数据写入（标准编号 + 中文名 + 业务定义 -> 4 路向量）

  4. 混合检索（稠密 top_k + 稀疏 top_k -> 合并去重）



环境说明：

  - VPN/梯子场景：gRPC（Milvus）走 HTTP 代理隧道，HF 下载绕过代理直连镜像

  - 代理连接不稳定时自动重试（最多 5 次，指数退避）

  - NumPy 2.x：numexpr/bottleneck/h5py 兼容性已处理

  - 模型下载：使用 hf-mirror.com 国内镜像；已缓存后自动离线加载

"""

import os

import sys

import time

import logging

import functools


# ============================================================

# 环境预处理（必须在 import pymilvus / transformers 之前执行）

# ============================================================


# 1. NumPy 2.x 兼容

sys.modules.setdefault("numexpr", None)

sys.modules.setdefault("bottleneck", None)


# 2. TRANSFORMERS_NO_TF / USE_TF 已移至 config.py（确保在 langchain 导入链之前生效）


from config import (
    MILVUS_URI,
    MILVUS_TOKEN,
    MILVUS_COLLECTION,
    TYPE_COLLECTION_MAP,
    MILVUS_PROXY,
    EMBED_MODEL_NAME,
    EMBED_DIMENSION,
    EMBED_QUERY_INSTRUCTION,
    EMBED_DEVICE,
)


# 3. 代理配置：必须在设置 NO_PROXY 之前执行


def _setup_proxy():

    if MILVUS_PROXY == "none":
        return

    if MILVUS_PROXY and MILVUS_PROXY != "auto":
        os.environ["HTTP_PROXY"] = MILVUS_PROXY

        os.environ["HTTPS_PROXY"] = MILVUS_PROXY

        return

    import urllib.request

    proxies = urllib.request.getproxies()

    http_proxy = proxies.get("http") or proxies.get("https")

    if http_proxy:
        os.environ["HTTP_PROXY"] = http_proxy

        os.environ["HTTPS_PROXY"] = http_proxy

        _logger.info("检测到系统代理: %s", http_proxy)


_logger = logging.getLogger(__name__)

_setup_proxy()


# 4. NO_PROXY：HF 域名绕过代理直连镜像（在 _setup_proxy 之后设置）

_hf_domains = (
    "hf-mirror.com,huggingface.co,cdn-lfs.huggingface.co,"
    "cdn-lfs-us-1.huggingface.co,cdn-lfs-eu-1.huggingface.co"
)

_existing = os.environ.get("NO_PROXY", "")

os.environ["NO_PROXY"] = _existing + "," + _hf_domains if _existing else _hf_domains


from pymilvus import MilvusClient, DataType, Function, FunctionType, MilvusException

from common.exceptions import (
    GovernanceError,
    NonRetryableError,
    MilvusAuthError,
    MilvusConnectionError,
    MilvusSchemaError,
)


# ============================================================

# 重试装饰器（VPN 代理连接不稳定时自动重试）

# ============================================================


MAX_RETRIES = 5

RETRY_BASE_DELAY = 3  # 秒


def translate_milvus_error(e: Exception) -> GovernanceError:
    """将 Milvus 原始异常翻译为分类异常，供重试与上层熔断判断。

    未识别的异常保守当作可重试的连接类错误（保持原有重试行为）。
    """
    if isinstance(e, GovernanceError):
        return e

    msg = str(e).lower()

    if isinstance(e, MilvusException):
        if any(k in msg for k in ("unauthenticated", "invalid credential", "permission", "authentication")):
            return MilvusAuthError(f"Milvus 鉴权失败，请检查 MILVUS_TOKEN: {e}")
        if any(k in msg for k in ("collection not found", "field not found", "dimension", "schema")):
            return MilvusSchemaError(f"Milvus schema 不匹配: {e}")

    return MilvusConnectionError(f"Milvus 连接/网络错误: {type(e).__name__}: {e}")


def with_retry(func):
    """带指数退避的重试装饰器；不可重试错误（鉴权/配置/schema）立刻抛出不重试。"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):

        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)

            except Exception as e:
                translated = translate_milvus_error(e)

                if isinstance(translated, NonRetryableError):
                    raise translated from e

                last_error = translated

                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2**attempt)

                    _logger.warning(
                        "操作失败 (尝试 %d/%d): %s，%ds 后重试...",
                        attempt + 1,
                        MAX_RETRIES,
                        type(translated).__name__,
                        delay,
                    )

                    time.sleep(delay)

                else:
                    _logger.error("操作失败，已达最大重试次数 %d", MAX_RETRIES)

        raise last_error

    return wrapper


# ============================================================

# 向量模型

# ============================================================


_embedder = None


def get_embedder():
    """懒加载 bge-large-zh-v1.5 模型（单例，CPU 推理）。"""

    global _embedder

    if _embedder is None:
        from sentence_transformers import SentenceTransformer

        _logger.info("加载向量模型: %s", EMBED_MODEL_NAME)

        _embedder = SentenceTransformer(EMBED_MODEL_NAME, device=EMBED_DEVICE)

        _logger.info(
            "模型加载完成，维度: %d",
            _embedder.get_sentence_embedding_dimension(),
        )

    return _embedder


def embed_texts(texts, is_query=False):
    """将文本列表转为稠密向量（1024 维）。


    Args:

        texts: 待向量化的文本列表

        is_query: True 时添加 BGE 检索指令前缀

    """

    model = get_embedder()

    if is_query:
        texts = [EMBED_QUERY_INSTRUCTION + t for t in texts]

    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=len(texts) > 100,
        batch_size=32,
    )

    return embeddings.tolist()


# ============================================================

# Milvus 集合管理

# ============================================================


_client = None
_loaded_collections = set()


@with_retry
def get_client():
    """获取 Milvus 客户端（单例，带重试）。"""

    global _client

    if _client is not None:
        # 验证连接是否还活着

        try:
            _client.list_collections()

            return _client

        except Exception:
            _client = None

    _client = MilvusClient(uri=MILVUS_URI, token=MILVUS_TOKEN, timeout=30)

    _logger.info("Milvus 连接成功: %s", _client.get_server_version())

    return _client


@with_retry
def create_collection(client, collection_name=None):
    """创建非代码枚举类字典向量集合（含 4 路向量 + 2 个 BM25 函数）。"""

    collection_name = collection_name or MILVUS_COLLECTION

    if client.has_collection(collection_name):
        _logger.info("集合 %s 已存在，跳过创建", collection_name)

        return

    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)

    schema.add_field("standard_id", DataType.VARCHAR, is_primary=True, max_length=20)

    schema.add_field(
        "name_text",
        DataType.VARCHAR,
        max_length=200,
        enable_analyzer=True,
        analyzer_params={"type": "chinese"},
    )

    schema.add_field("name_dense", DataType.FLOAT_VECTOR, dim=EMBED_DIMENSION)

    schema.add_field("name_sparse", DataType.SPARSE_FLOAT_VECTOR, max_length=1000)

    schema.add_field(
        "meaning_text",
        DataType.VARCHAR,
        max_length=4000,
        enable_analyzer=True,
        analyzer_params={"type": "chinese"},
    )

    schema.add_field("meaning_dense", DataType.FLOAT_VECTOR, dim=EMBED_DIMENSION)

    schema.add_field("meaning_sparse", DataType.SPARSE_FLOAT_VECTOR, max_length=1000)

    schema.add_function(
        Function(
            name="name_bm25",
            function_type=FunctionType.BM25,
            input_field_names=["name_text"],
            output_field_names=["name_sparse"],
        )
    )

    schema.add_function(
        Function(
            name="meaning_bm25",
            function_type=FunctionType.BM25,
            input_field_names=["meaning_text"],
            output_field_names=["meaning_sparse"],
        )
    )

    index_params = client.prepare_index_params()

    index_params.add_index(
        field_name="name_dense",
        index_type="HNSW",
        metric_type="COSINE",
        params={"M": 16, "efConstruction": 200},
    )

    index_params.add_index(
        field_name="meaning_dense",
        index_type="HNSW",
        metric_type="COSINE",
        params={"M": 16, "efConstruction": 200},
    )

    index_params.add_index(
        field_name="name_sparse",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
    )

    index_params.add_index(
        field_name="meaning_sparse",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
    )

    client.create_collection(
        collection_name=collection_name,
        schema=schema,
        index_params=index_params,
    )

    _logger.info("集合 %s 创建成功", collection_name)


def drop_collection(client, collection_name=None):
    """删除集合。"""

    collection_name = collection_name or MILVUS_COLLECTION

    if client.has_collection(collection_name):
        client.drop_collection(collection_name)

        _logger.info("集合 %s 已删除", collection_name)


@with_retry
def ensure_loaded(client, collection_name=None):
    """确保集合已加载到内存（检索前必须加载）。

    使用模块级集合缓存已加载的 collection，避免重复调用 load_collection。
    """

    collection_name = collection_name or MILVUS_COLLECTION

    if collection_name in _loaded_collections:
        return

    # 显式按 1 副本加载：单节点部署只有 1 个 streaming node，
    # 服务端默认副本数 > 1 时会报 service resource insufficient
    client.load_collection(collection_name, replica_number=1)
    _loaded_collections.add(collection_name)


# ============================================================

# 数据写入

# ============================================================


def insert_standards(client, records, collection_name=None, batch_size=500):
    """批量写入字典标准到 Milvus（带重试）。"""

    collection_name = collection_name or MILVUS_COLLECTION

    total = len(records)

    for i in range(0, total, batch_size):
        batch = records[i : i + batch_size]

        @with_retry
        def _upsert():

            client.upsert(collection_name=collection_name, data=batch)

        _upsert()

        done = min(i + batch_size, total)

        _logger.info("写入进度: %d/%d", done, total)

    _logger.info("写入完成，共 %d 条", total)


# ============================================================

# 检索

# ============================================================


@with_retry
def search(query_name, query_meaning, top_k=10, field_type=None, collection_name=None, client=None):
    """混合检索：稠密 top_k + 稀疏 top_k -> 合并去重。



    检索流程：

      1. 稠密检索：name_dense + meaning_dense 各取 top_k*3，

         按 0.5/0.5 权重合并得分，取 top_k

      2. 稀疏检索：name_sparse + meaning_sparse 各取 top_k*3，

         按 0.5/0.5 权重合并得分，取 top_k

      3. 两路 top_k 合并，按 standard_id 去重



    Args:

        query_name: 查询字段中文名

        query_meaning: 查询业务含义

        top_k: 每路返回数量（默认 10）



    Returns:

        合并去重后的结果列表，每条含:

        standard_id, name_text, meaning_text,

        dense_score, sparse_score, source("dense"/"sparse"/"both")

    """

    if collection_name is None:
        if field_type not in TYPE_COLLECTION_MAP:
            raise ValueError(
                f"不支持的字段类型: {field_type}，"
                f"支持的类型: {list(TYPE_COLLECTION_MAP.keys())}"
            )
        collection_name = TYPE_COLLECTION_MAP[field_type]

    if client is None:
        client = get_client()

    ensure_loaded(client, collection_name)

    output_fields = ["standard_id", "name_text", "meaning_text"]

    sub_limit = top_k * 3

    # --- 1. 稠密检索 ---

    query_vecs = embed_texts([query_name, query_meaning], is_query=True)

    name_vec, meaning_vec = query_vecs[0], query_vecs[1]

    name_dense_res = client.search(
        collection_name=collection_name,
        data=[name_vec],
        anns_field="name_dense",
        limit=sub_limit,
        output_fields=output_fields,
    )

    meaning_dense_res = client.search(
        collection_name=collection_name,
        data=[meaning_vec],
        anns_field="meaning_dense",
        limit=sub_limit,
        output_fields=output_fields,
    )

    dense_map = {}

    for hit in name_dense_res[0]:
        sid = hit["standard_id"]

        dense_map[sid] = {
            "name_text": hit["entity"]["name_text"],
            "meaning_text": hit["entity"]["meaning_text"],
            "score": 0.5 * hit["distance"],
        }

    for hit in meaning_dense_res[0]:
        sid = hit["standard_id"]

        if sid in dense_map:
            dense_map[sid]["score"] += 0.5 * hit["distance"]

        else:
            dense_map[sid] = {
                "name_text": hit["entity"]["name_text"],
                "meaning_text": hit["entity"]["meaning_text"],
                "score": 0.5 * hit["distance"],
            }

    dense_top = sorted(dense_map.items(), key=lambda x: -x[1]["score"])[:top_k]

    # --- 2. 稀疏检索 (BM25) ---

    name_sparse_res = client.search(
        collection_name=collection_name,
        data=[query_name],
        anns_field="name_sparse",
        limit=sub_limit,
        output_fields=output_fields,
    )

    meaning_sparse_res = client.search(
        collection_name=collection_name,
        data=[query_meaning],
        anns_field="meaning_sparse",
        limit=sub_limit,
        output_fields=output_fields,
    )

    sparse_map = {}

    for hit in name_sparse_res[0]:
        sid = hit["standard_id"]

        sparse_map[sid] = {
            "name_text": hit["entity"]["name_text"],
            "meaning_text": hit["entity"]["meaning_text"],
            "score": 0.5 * hit["distance"],
        }

    for hit in meaning_sparse_res[0]:
        sid = hit["standard_id"]

        if sid in sparse_map:
            sparse_map[sid]["score"] += 0.5 * hit["distance"]

        else:
            sparse_map[sid] = {
                "name_text": hit["entity"]["name_text"],
                "meaning_text": hit["entity"]["meaning_text"],
                "score": 0.5 * hit["distance"],
            }

    sparse_top = sorted(sparse_map.items(), key=lambda x: -x[1]["score"])[:top_k]

    # --- 3. 合并去重 ---

    results = {}

    for sid, info in dense_top:
        results[sid] = {
            "standard_id": sid,
            "name_text": info["name_text"],
            "meaning_text": info["meaning_text"],
            "dense_score": round(info["score"], 4),
            "sparse_score": 0.0,
            "source": "dense",
        }

    for sid, info in sparse_top:
        if sid in results:
            results[sid]["sparse_score"] = round(info["score"], 4)

            results[sid]["source"] = "both"

        else:
            results[sid] = {
                "standard_id": sid,
                "name_text": info["name_text"],
                "meaning_text": info["meaning_text"],
                "dense_score": 0.0,
                "sparse_score": round(info["score"], 4),
                "source": "sparse",
            }

    return list(results.values())
