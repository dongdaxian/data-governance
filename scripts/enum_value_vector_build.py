# -*- coding: utf-8 -*-
"""枚举值码值向量集合构建脚本 -- 构建 dict_enum_values。

存储粒度是"枚举值项"，item_id 为枚举代码编号（枚举值编号，形如 ENM00001）：
  - 每个代码枚举类标准对应一个枚举代码，枚举代码的枚举值来自该标准的"业务规则"
  - 同一枚举代码可能被多个标准引用，按枚举值编号分组去重

每条记录主键：item_id + 码（auto_id 主键）

用法（在项目根目录执行，需 Milvus 运行中）：
  python scripts/enum_value_vector_build.py                # 增量构建（insert）
  python scripts/enum_value_vector_build.py --limit 10     # 仅处理前 10 个枚举值项（测试用）
  python scripts/enum_value_vector_build.py --rebuild      # 删除已有集合后重建
  python scripts/enum_value_vector_build.py --dry-run      # 仅解析与向量化，不写入
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymilvus import DataType

from config import (
    ENUM_VALUE_COLLECTION,
    DICTIONARY_PATH,
    EMBED_DIMENSION,
)
from common.vector_store import (
    get_client,
    drop_collection,
    embed_texts,
    get_embedder,
    with_retry,
)
from enum_standard_mapping.enum_store import parse_valid_enum_pairs

import pandas as pd

# ============================================================
# 字典加载与枚举值项拆分
# ============================================================

def load_enum_items(limit=None):
    """加载全量字典，拆分为枚举值项（按枚举代码编号）。

    Returns:
        items: [{"item_id": 枚举代码编号(ENM), "item_name": 标准中文名称,
                 "pairs": [(码,值)...]}, ...]
    """
    df = pd.read_excel(DICTIONARY_PATH, sheet_name="全量字典", dtype=str)
    enum_df = df[df["标准所属类型"] == "代码枚举类"]
    print(f"代码枚举类字典: {len(enum_df)} 条")

    # 按枚举代码编号聚合（同一枚举代码可能被多个标准引用）。
    # 逐行读取 Excel 的同时解析并筛除无效码值对（与 nodes.py 回填时的过滤一致）
    groups = {}
    skipped = 0
    for _, row in enum_df.iterrows():
        enm_id = str(row.get("枚举值编号", "")).strip()
        std_name = str(row.get("标准中文名称", "")).strip()
        rule = str(row.get("业务规则", "")).strip() if pd.notna(row.get("业务规则")) else ""
        if not enm_id:
            # 无枚举代码编号的标准不入库（无效信息）
            continue
        pairs = parse_valid_enum_pairs(rule)
        if not pairs:
            # 枚举值定义无效（引用文本/无有效码值对）→ 视为该标准不存在，不入库
            skipped += 1
            continue
        if enm_id not in groups:
            groups[enm_id] = {
                "item_id": enm_id,
                "item_name": std_name,
                "pairs": pairs,
            }

    items = list(groups.values())
    print(f"枚举值项: {len(items)} 个（剔除无有效枚举值定义的标准 {skipped} 条）")

    if limit:
        items = items[:limit]
        print(f"  --limit 生效: 仅处理前 {len(items)} 个枚举值项")

    return items


def build_records(items):
    """将枚举值项展开为 Milvus 记录（码值去重后向量化）。

    记录结构：
      item_id: 枚举代码编号
      code: 码
      value_text: 码值文本
      value_dense: 向量
    """
    records = []
    # 收集待向量化文本（去重）
    text_set = {}
    for item in items:
        for code, value in item["pairs"]:
            if not value:
                continue
            text_set[value] = None

    texts = list(text_set.keys())
    print(f"待向量化文本: {len(texts)} 条（去重后）")
    get_embedder()  # 预加载模型
    embeddings = embed_texts(texts, is_query=False)
    vec_map = dict(zip(texts, embeddings))

    for item in items:
        for code, value in item["pairs"]:
            if not value:
                continue
            records.append({
                "item_id": item["item_id"],
                "code": code,
                "value_text": value,
                "value_dense": vec_map[value],
            })

    print(f"Milvus 记录总数: {len(records)} 条")
    return records


# ============================================================
# 集合创建
# ============================================================

def create_enum_collection(client):
    """创建 dict_enum_values 集合（稠密向量 + 标量标签）。"""
    if client.has_collection(ENUM_VALUE_COLLECTION):
        print(f"集合 {ENUM_VALUE_COLLECTION} 已存在")
        return

    schema = client.create_schema(auto_id=True, enable_dynamic_field=False)
    schema.add_field("pk", DataType.INT64, is_primary=True, auto_id=True)
    schema.add_field("item_id", DataType.VARCHAR, max_length=20)
    schema.add_field("code", DataType.VARCHAR, max_length=50)
    schema.add_field("value_text", DataType.VARCHAR, max_length=500)
    schema.add_field("value_dense", DataType.FLOAT_VECTOR, dim=EMBED_DIMENSION)

    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="value_dense",
        index_type="HNSW",
        metric_type="COSINE",
        params={"M": 16, "efConstruction": 200},
    )
    # 先建集合：不传 index_params，避免 create_collection 内部自动 load_collection
    # （MilvusClient 自动 load 用默认副本数 2，单节点部署会报 service resource insufficient）
    client.create_collection(
        collection_name=ENUM_VALUE_COLLECTION,
        schema=schema,
        index_params=None,
    )
    # 再单独建索引（建索引不触发 load，加载由检索时的 ensure_loaded 按副本数 1 完成）
    client.create_index(collection_name=ENUM_VALUE_COLLECTION, index_params=index_params)
    print(f"集合 {ENUM_VALUE_COLLECTION} 创建成功")


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="构建枚举值码值向量集合")
    parser.add_argument("--limit", type=int, default=None, help="仅处理前 N 个枚举值项（测试用）")
    parser.add_argument("--rebuild", action="store_true", help="删除已有集合后重建")
    parser.add_argument("--dry-run", action="store_true", help="仅解析与向量化，不写入")
    args = parser.parse_args()

    items = load_enum_items(limit=args.limit)
    records = build_records(items)

    if args.dry_run:
        print("dry-run 模式，不写入 Milvus")
        return

    client = get_client()

    if args.rebuild:
        drop_collection(client, ENUM_VALUE_COLLECTION)

    create_enum_collection(client)

    # 批量写入
    batch_size = 500
    total = len(records)
    for i in range(0, total, batch_size):
        batch = records[i : i + batch_size]

        @with_retry
        def _insert():
            client.insert(collection_name=ENUM_VALUE_COLLECTION, data=batch)

        _insert()
        done = min(i + batch_size, total)
        print(f"写入进度: {done}/{total}")

    # 稠密索引无需 load 前置 flush，但为首次检索预热
    client.flush(ENUM_VALUE_COLLECTION)
    print(f"完成，共写入 {total} 条")


if __name__ == "__main__":
    main()
