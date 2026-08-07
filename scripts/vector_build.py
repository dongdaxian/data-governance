# -*- coding: utf-8 -*-
"""向量库构建脚本 -- 从全量字典构建非代码枚举类向量索引。

流程：
  1. 读取全量字典_最终.xlsx，筛选非代码枚举类，按字段所属类型分组
  2. bge-large-zh-v1.5 向量化（字段中文名 + 业务定义）
  3. 按类型写入对应的 Milvus 集合（dict_encode/text/number/datetime/flag）
  4. 稠密向量备份到 Parquet（按类型分文件，Milvus 试用期 1 个月）
  5. 检索验证

用法：
  # 测试模式（仅处理 10 条/类型）
  python scripts/vector_build.py --limit 10

  # 全量模式
  python scripts/vector_build.py

  # 自定义输入文件
  python scripts/vector_build.py --input path/to/dict.xlsx

  # 清理旧的 dict_non_enum 集合
  python scripts/vector_build.py --cleanup-legacy
"""

import argparse
import os
import sys
import time

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.vector_store import (
    get_client,
    create_collection,
    embed_texts,
    insert_standards,
    backup_to_parquet,
    search,
    ensure_loaded,
    drop_collection,
)
from config import TYPE_COLLECTION_MAP

# 非代码枚举类类型（与 TYPE_COLLECTION_MAP 的 key 一致）
NON_ENUM_TYPES = set(TYPE_COLLECTION_MAP.keys())

DICT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "dictionary_mock",
    "全量字典_最终.xlsx",
)

LEGACY_COLLECTION = "dict_non_enum"

VECTOR_BACKUP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "vector_backup",
)


def load_records(dict_path, limit=None):
    """从 Excel 读取非代码枚举类字典记录，按字段所属类型分组。

    Returns:
        {field_type: [records]} 的字典，每条 record 含
        standard_id, name_text, meaning_text
    """
    import pandas as pd

    df = pd.read_excel(dict_path, sheet_name="全量字典")
    df = df[df["标准所属类型"].isin(NON_ENUM_TYPES)].copy()

    # 清洗
    df = df.dropna(subset=["标准编号", "标准中文名称", "业务定义"])
    df["标准编号"] = df["标准编号"].astype(str).str.strip()
    df["标准中文名称"] = df["标准中文名称"].astype(str).str.strip()
    df["业务定义"] = df["业务定义"].astype(str).str.strip()
    df = df[df["标准编号"].str.len() > 0]
    df = df[df["标准中文名称"].str.len() > 0]
    df = df[df["业务定义"].str.len() > 0]

    grouped = {}
    for ftype, group in df.groupby("标准所属类型"):
        records = []
        for _, row in group.iterrows():
            records.append(
                {
                    "standard_id": row["标准编号"],
                    "name_text": row["标准中文名称"],
                    "meaning_text": row["业务定义"][:4000],
                }
            )
        if limit:
            records = records[:limit]
        grouped[ftype] = records

    total = sum(len(v) for v in grouped.values())
    print(f"加载 {total} 条非代码枚举类字典记录，按类型分组：")
    for ftype in TYPE_COLLECTION_MAP:
        if ftype in grouped:
            print(f"  {ftype}: {len(grouped[ftype])} 条 -> {TYPE_COLLECTION_MAP[ftype]}")
    return grouped


def build_vectors(records):
    """向量化并组装 Milvus 记录（填充 name_dense, meaning_dense）。"""
    names = [r["name_text"] for r in records]
    meanings = [r["meaning_text"] for r in records]

    print(f"  向量化字段中文名 ({len(names)} 条)...")
    t0 = time.time()
    name_vecs = embed_texts(names, is_query=False)
    print(f"    完成，耗时 {time.time() - t0:.1f}s")

    print(f"  向量化业务定义 ({len(meanings)} 条)...")
    t0 = time.time()
    meaning_vecs = embed_texts(meanings, is_query=False)
    print(f"    完成，耗时 {time.time() - t0:.1f}s")

    for i, r in enumerate(records):
        r["name_dense"] = name_vecs[i]
        r["meaning_dense"] = meaning_vecs[i]

    return records


def _print_results(results):
    """格式化打印检索结果。"""
    for r in results:
        src = r["source"]
        sid = r["standard_id"]
        name = r["name_text"]
        dense = r["dense_score"]
        sparse = r["sparse_score"]
        print(f"    [{src}] {sid} {name} (dense={dense}, sparse={sparse})")


def main():
    parser = argparse.ArgumentParser(description="构建非代码枚举类字典向量库")
    parser.add_argument(
        "--input", "-i", default=DICT_PATH, help="输入 Excel 文件路径"
    )
    parser.add_argument(
        "--limit", "-n", type=int, default=None, help="仅处理前 N 条/类型（测试用）"
    )
    parser.add_argument(
        "--no-backup", action="store_true", help="不备份 Parquet"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="仅向量化，不写入 Milvus"
    )
    parser.add_argument(
        "--cleanup-legacy", action="store_true",
        help="删除旧的 dict_non_enum 集合后退出",
    )
    args = parser.parse_args()

    client = get_client()

    # 清理旧集合
    if args.cleanup_legacy:
        drop_collection(client, collection_name=LEGACY_COLLECTION)
        print(f"已删除旧集合: {LEGACY_COLLECTION}")
        return

    # 1. 加载数据（按类型分组）
    grouped = load_records(args.input, limit=args.limit)
    if not grouped:
        print("无数据可处理")
        return

    total_processed = 0

    for ftype, records in grouped.items():
        collection_name = TYPE_COLLECTION_MAP[ftype]
        print(f"\n{'=' * 50}")
        print(f"处理 [{ftype}] -> collection: {collection_name} ({len(records)} 条)")
        print(f"{'=' * 50}")

        # 2. 向量化
        records = build_vectors(records)

        if args.dry_run:
            print("  --dry-run 模式，跳过写入 Milvus")
            total_processed += len(records)
            continue

        # 3. 写入 Milvus
        create_collection(client, collection_name=collection_name)
        print(f"  写入 Milvus...")
        insert_standards(client, records, collection_name=collection_name)

        # 4. Parquet 备份（按类型分文件）
        if not args.no_backup:
            os.makedirs(VECTOR_BACKUP_DIR, exist_ok=True)
            backup_path = backup_to_parquet(
                records,
                filepath=os.path.join(VECTOR_BACKUP_DIR, f"{collection_name}.parquet"),
            )
            print(f"  Parquet 备份: {backup_path}")

        # 5. 检索验证
        print(f"  --- 检索验证 ---")
        ensure_loaded(client, collection_name=collection_name)
        test_name = records[0]["name_text"]
        test_meaning = records[0]["meaning_text"]
        print(f"  查询: name={test_name}")
        results = search(
            test_name,
            test_meaning,
            top_k=5,
            field_type=ftype,
            client=client,
        )
        _print_results(results)

        total_processed += len(records)

    print(f"\n完成！共处理 {total_processed} 条，涉及 {len(grouped)} 个类型")


if __name__ == "__main__":
    main()
