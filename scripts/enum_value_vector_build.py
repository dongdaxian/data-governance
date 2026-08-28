# -*- coding: utf-8 -*-
"""枚举值码值向量集合构建脚本 -- 构建 dict_enum_values。

存储粒度是"枚举值项"：
  - 有域字典：按域去重存，标签 = 域编号，item_type = "domain"，附带名下字典清单（standards 字段）
  - 无域字典：按字典自身存，标签 = 标准编号，item_type = "standard"
  - 字典名称条目：item_type = "name"，服务降级检索（A 方案），不参与枚举值打分

每条记录主键：item_type + item 编号 + 码（域内唯一）

用法（在项目根目录执行，需 Milvus 运行中）：
  python scripts/enum_value_vector_build.py                # 增量构建（upsert）
  python scripts/enum_value_vector_build.py --limit 10     # 仅处理前 10 个枚举值项（测试用）
  python scripts/enum_value_vector_build.py --rebuild      # 删除已有集合后重建
  python scripts/enum_value_vector_build.py --dry-run      # 仅解析与向量化，不写入
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymilvus import DataType, Function, FunctionType

from config import (
    ENUM_VALUE_COLLECTION,
    DICTIONARY_PATH,
    EMBED_DIMENSION,
)
from common.vector_store import (
    get_client,
    create_collection as _create_base_collection,
    drop_collection,
    embed_texts,
    get_embedder,
    with_retry,
)
from enum_standard_mapping.domain_store import parse_enum_values

import pandas as pd

# ============================================================
# 字典加载与枚举值项拆分
# ============================================================

def load_enum_items(limit=None):
    """加载全量字典，拆分为枚举值项 + 名称条目。

    Returns:
        (items, name_entries)
        items: [{"item_id": 域编号或标准编号, "item_type": "domain"/"standard",
                 "item_name": 域名称或标准名称, "pairs": [(码,值)...],
                 "standards": [(标准编号, 标准名称)...名下字典清单]}, ...]
        name_entries: [{"item_id": 标准编号, "value_text": 标准中文名称}, ...]
    """
    df = pd.read_excel(DICTIONARY_PATH, sheet_name="全量字典", dtype=str)
    enum_df = df[df["标准所属类型"] == "代码枚举类"]
    print(f"代码枚举类字典: {len(enum_df)} 条")

    # 按域聚合（域编号为空 = 无域字典）
    domain_groups = {}
    standalone = []
    for _, row in enum_df.iterrows():
        std_id = str(row.get("标准编号", "")).strip()
        std_name = str(row.get("标准中文名称", "")).strip()
        domain_id = str(row.get("域编号", "")).strip() if pd.notna(row.get("域编号")) else ""
        domain_name = str(row.get("域名称", "")).strip() if pd.notna(row.get("域名称")) else ""
        rule = str(row.get("业务规则", "")).strip() if pd.notna(row.get("业务规则")) else ""

        # 名称条目（降级检索用）：每个字典一条
        # 在函数末统一收集

        if domain_id:
            if domain_id not in domain_groups:
                domain_groups[domain_id] = {
                    "item_id": domain_id,
                    "item_type": "domain",
                    "item_name": domain_name,
                    "pairs": parse_enum_values(rule),
                    "standards": [],
                }
            domain_groups[domain_id]["standards"].append((std_id, std_name))
        else:
            standalone.append({
                "item_id": std_id,
                "item_type": "standard",
                "item_name": std_name,
                "pairs": parse_enum_values(rule),
                "standards": [(std_id, std_name)],
            })

    items = list(domain_groups.values()) + standalone
    name_entries = [
        {"item_id": str(r["标准编号"]).strip(), "value_text": str(r["标准中文名称"]).strip()}
        for _, r in enum_df.iterrows()
    ]

    # 剔除无枚举值定义的项
    items = [it for it in items if it["pairs"]]
    print(f"枚举值项: {len(items)} 个（域 {len(domain_groups)} 个 + 无域字典 {len(standalone)} 个），名称条目 {len(name_entries)} 条")

    if limit:
        items = items[:limit]
        name_entries = name_entries[:limit * 3]
        print(f"  --limit 生效: 仅处理前 {len(items)} 个枚举值项 / {len(name_entries)} 条名称条目")

    return items, name_entries


def build_records(items, name_entries):
    """将枚举值项展开为 Milvus 记录（码值去重后向量化）。

    记录结构：
      item_id: 枚举值项编号（域编号/标准编号）
      item_type: domain / standard / name
      code: 码
      value_text: 码值文本（名称条目 = 标准中文名称）
      value_dense: 向量
      standards: 名下字典清单 "编号:名称|编号:名称"（仅 domain/standard，name 为空）
      item_name: 项名称（域名称/标准名称）
    """
    records = []
    # 收集待向量化文本（去重）
    text_set = {}

    for item in items:
        for code, value in item["pairs"]:
            if not value:
                continue
            text_set[value] = None
        # 项名称不参与向量化（存 item_name 标量字段）

    for entry in name_entries:
        if entry["value_text"]:
            text_set[entry["value_text"]] = None

    texts = list(text_set.keys())
    print(f"待向量化文本: {len(texts)} 条（去重后）")
    get_embedder()  # 预加载模型
    embeddings = embed_texts(texts, is_query=False)
    vec_map = dict(zip(texts, embeddings))

    for item in items:
        standards_str = "|".join(f"{sid}:{sname}" for sid, sname in item["standards"])
        for code, value in item["pairs"]:
            if not value:
                continue
            records.append({
                "item_id": item["item_id"],
                "item_type": item["item_type"],
                "code": code,
                "value_text": value,
                "value_dense": vec_map[value],
                "standards": standards_str[:2000],
                "item_name": item["item_name"][:200],
            })

    for entry in name_entries:
        if entry["value_text"]:
            records.append({
                "item_id": entry["item_id"],
                "item_type": "name",
                "code": "",
                "value_text": entry["value_text"],
                "value_dense": vec_map[entry["value_text"]],
                "standards": "",
                "item_name": "",
            })

    print(f"Milvus 记录总数: {len(records)} 条（码值 {len(records) - len(name_entries)} + 名称 {len(name_entries)}）")
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
    schema.add_field("item_type", DataType.VARCHAR, max_length=10)
    schema.add_field("code", DataType.VARCHAR, max_length=50)
    schema.add_field("value_text", DataType.VARCHAR, max_length=500)
    schema.add_field("value_dense", DataType.FLOAT_VECTOR, dim=EMBED_DIMENSION)
    schema.add_field("standards", DataType.VARCHAR, max_length=2000)
    schema.add_field("item_name", DataType.VARCHAR, max_length=200)

    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="value_dense",
        index_type="HNSW",
        metric_type="COSINE",
        params={"M": 16, "efConstruction": 200},
    )
    client.create_collection(
        collection_name=ENUM_VALUE_COLLECTION,
        schema=schema,
        index_params=index_params,
    )
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

    items, name_entries = load_enum_items(limit=args.limit)
    records = build_records(items, name_entries)

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
