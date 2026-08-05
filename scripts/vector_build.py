# -*- coding: utf-8 -*-
"""向量库构建脚本 -- 从全量字典构建非代码枚举类向量索引。

流程：
  1. 读取全量字典_最终.xlsx，筛选非代码枚举类
  2. bge-large-zh-v1.5 向量化（字段中文名 + 业务定义）
  3. 写入 Milvus 集合（稠密向量 + BM25 稀疏向量）
  4. 稠密向量备份到 Parquet（Milvus 试用期 1 个月）
  5. 检索验证

用法：
  # 测试模式（仅处理 10 条）
  python scripts/vector_build.py --limit 10

  # 全量模式
  python scripts/vector_build.py

  # 自定义输入文件 + 集合名
  python scripts/vector_build.py --input path/to/dict.xlsx --collection my_col
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
)

# 非代码枚举类类型
NON_ENUM_TYPES = {"编码类", "文本类", "数值类", "日期时间类", "标志类"}

DICT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "dictionary_mock",
    "全量字典_最终.xlsx",
)


def load_records(dict_path, limit=None):
    """从 Excel 读取非代码枚举类字典记录。

    Returns:
        记录列表，每条含 standard_id, name_text, meaning_text
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

    if limit:
        df = df.head(limit)

    records = []
    for _, row in df.iterrows():
        records.append(
            {
                "standard_id": row["标准编号"],
                "name_text": row["标准中文名称"],
                "meaning_text": row["业务定义"][:4000],
            }
        )

    print(f"加载 {len(records)} 条非代码枚举类字典记录")
    return records


def build_vectors(records):
    """向量化并组装 Milvus 记录（填充 name_dense, meaning_dense）。"""
    names = [r["name_text"] for r in records]
    meanings = [r["meaning_text"] for r in records]

    print(f"向量化字段中文名 ({len(names)} 条)...")
    t0 = time.time()
    name_vecs = embed_texts(names, is_query=False)
    print(f"  完成，耗时 {time.time() - t0:.1f}s")

    print(f"向量化业务定义 ({len(meanings)} 条)...")
    t0 = time.time()
    meaning_vecs = embed_texts(meanings, is_query=False)
    print(f"  完成，耗时 {time.time() - t0:.1f}s")

    for i, r in enumerate(records):
        r["name_dense"] = name_vecs[i]
        r["meaning_dense"] = meaning_vecs[i]

    return records


def main():
    parser = argparse.ArgumentParser(description="构建非代码枚举类字典向量库")
    parser.add_argument(
        "--input", "-i", default=DICT_PATH, help="输入 Excel 文件路径"
    )
    parser.add_argument(
        "--limit", "-n", type=int, default=None, help="仅处理前 N 条（测试用）"
    )
    parser.add_argument(
        "--collection", "-c", default=None, help="Milvus 集合名称"
    )
    parser.add_argument(
        "--no-backup", action="store_true", help="不备份 Parquet"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="仅向量化，不写入 Milvus"
    )
    args = parser.parse_args()

    # 1. 加载数据
    records = load_records(args.input, limit=args.limit)
    if not records:
        print("无数据可处理")
        return

    # 2. 向量化
    records = build_vectors(records)

    if args.dry_run:
        print("--dry-run 模式，跳过写入 Milvus")
        return

    # 3. 写入 Milvus
    client = get_client()
    create_collection(client, collection_name=args.collection)
    print("写入 Milvus...")
    insert_standards(client, records, collection_name=args.collection)

    # 4. Parquet 备份
    if not args.no_backup:
        path = backup_to_parquet(records)
        print(f"Parquet 备份: {path}")

    # 5. 检索验证
    print("\n--- 检索验证 ---")
    ensure_loaded(client, collection_name=args.collection)
    test_name = records[0]["name_text"]
    test_meaning = records[0]["meaning_text"]
    print(f"查询: name={test_name}")
    results = search(
        test_name,
        test_meaning,
        top_k=5,
        collection_name=args.collection,
        client=client,
    )
    for r in results:
        print(
            f"  [{r['source']}] {r['standard_id']} {r['name_text']} "
            f"(dense={r['dense_score']}, sparse={r['sparse_score']})"
        )

    print(f"\n完成！共处理 {len(records)} 条")


if __name__ == "__main__":
    main()
