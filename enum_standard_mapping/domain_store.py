# -*- coding: utf-8 -*-
"""枚举值向量集合的检索与打分 -- 阶段 1 核心逻辑。

集合 dict_enum_values 的存储粒度是"枚举值项"：
  - 有域字典：按域去重存，标签 = 域编号，entity_type = "domain"
  - 无域字典：按字典自身存，标签 = 标准编号，entity_type = "standard"
  - 字典名称条目：服务降级检索（A方案），entity_type = "name"，不参与枚举值打分

打分规则（二值制）：
  字段 n 条码值逐条向量检索，相似度 >= 阈值计"命中"1 分
  枚举值项得分 = 命中条数（满分 n），未命中数 >= ceil(n/2) 出局
"""

import math
import logging
from collections import defaultdict

from config import (
    ENUM_VALUE_COLLECTION,
    ENUM_VALUE_MATCH_THRESHOLD,
    ENUM_CANDIDATE_TOP_N,
    ENUM_VALUE_SEARCH_TOP_K,
)

from common.vector_store import (
    get_client,
    ensure_loaded,
    embed_texts,
)

_logger = logging.getLogger(__name__)

# 检索输出字段
_OUTPUT_FIELDS = [
    "item_id",
    "item_type",
    "value_text",
]


# ============================================================
# 枚举值解析
# ============================================================

def parse_enum_values(enum_text: str) -> list[tuple[str, str]]:
    """解析格式化枚举值为 (码, 值) 列表。

    输入格式（质检输出标准化后）：码-值;码-值;...（如 1-男;2-女;0-未知）
    值内部分隔符不在解析范围（质检阶段已处理）。
    """
    if not enum_text:
        return []
    pairs = []
    for part in str(enum_text).split(";"):
        part = part.strip()
        if not part:
            continue
        # 码-值：取第一个 "-" 前为码，其余为值
        if "-" in part:
            code, value = part.split("-", 1)
            pairs.append((code.strip(), value.strip()))
        else:
            # 无 "-" 分隔的异常项：整段作为值，码为空
            pairs.append(("", part))
    return pairs


# ============================================================
# 枚举值项打分（阶段 1 核心）
# ============================================================

def _batch_search_values(value_texts: list[str]) -> dict[str, list[dict]]:
    """将字段 n 条码值文本批量向量检索，返回 {码值文本: [命中条目...]}。

    每条命中条目含 item_id / item_type / 相似度得分。
    相似度 < ENUM_VALUE_MATCH_THRESHOLD 的条目丢弃（不计命中）。
    """
    if not value_texts:
        return {}

    client = get_client()
    ensure_loaded(client, ENUM_VALUE_COLLECTION)

    # 批量向量化（query 模式）+ 一次多向量检索
    query_vecs = embed_texts(value_texts, is_query=True)
    results = client.search(
        collection_name=ENUM_VALUE_COLLECTION,
        data=query_vecs,
        anns_field="value_dense",
        limit=ENUM_VALUE_SEARCH_TOP_K,
        output_fields=_OUTPUT_FIELDS,
        filter='item_type != "name"',
    )

    hits_by_text = {}
    for text, hits in zip(value_texts, results):
        kept = []
        for hit in hits:
            score = hit["distance"]
            if score >= ENUM_VALUE_MATCH_THRESHOLD:
                kept.append({
                    "item_id": hit["entity"]["item_id"],
                    "item_type": hit["entity"]["item_type"],
                    "score": score,
                })
        if kept:
            hits_by_text[text] = kept
    return hits_by_text


def score_enum_items(pairs: list[tuple[str, str]]) -> dict:
    """对一个待落标字段的 n 条 (码, 值) 全库打分。

    Returns:
        {
          "hits_by_value": {值文本: [命中item...]},   # 阈值过滤后的检索结果
          "item_scores": {item_id: {"score": int, "matched": [(码,值)...]}},
          "value_unmatched": [值文本...],             # 全库未命中的字段码值
        }
    """
    value_texts = [v for _, v in pairs]
    hits_by_value = _batch_search_values(value_texts)

    # 按 item 聚合得分
    item_scores = defaultdict(lambda: {"score": 0, "matched": [], "item_type": ""})
    for code, value in pairs:
        hits = hits_by_value.get(value)
        if not hits:
            continue
        matched_items = set()
        for h in hits:
            iid = h["item_id"]
            item_scores[iid]["score"] += 1
            if not item_scores[iid]["item_type"]:
                item_scores[iid]["item_type"] = h.get("item_type", "")
            matched_items.add(iid)
        for item_id in matched_items:
            item_scores[item_id]["matched"].append((code, value))

    unmatched = [v for _, v in pairs if v not in hits_by_value]
    return {
        "hits_by_value": hits_by_value,
        "item_scores": dict(item_scores),
        "value_unmatched": unmatched,
    }


def eliminate_and_rank(item_scores: dict, n: int) -> list[dict]:
    """淘汰未过半数线的枚举值项，按得分排序（并列保持稳定序）。

    淘汰规则：未命中数 >= ceil(n/2)，等价于 score <= floor(n/2)。
    n=0 时返回空。
    """
    if n <= 0:
        return []
    min_score = math.floor(n / 2) + 1  # 存活线：score >= floor(n/2)+1
    survivors = []
    for item_id, info in item_scores.items():
        if info["score"] >= min_score:
            survivors.append({
                "item_id": item_id,
                "score": info["score"],
                "matched": info["matched"],
                "item_type": info.get("item_type", ""),
            })
    survivors.sort(key=lambda x: (-x["score"], x["item_id"]))
    return survivors


def top_n_with_ties(ranked: list[dict], top_n: int) -> list[dict]:
    """取前 top_n 名（含并列）：第 top_n 名之后得分与之相同的也保留。"""
    if not ranked or top_n <= 0:
        return []
    if len(ranked) <= top_n:
        return ranked
    cutoff_score = ranked[top_n - 1]["score"]
    result = ranked[:top_n]
    for item in ranked[top_n:]:
        if item["score"] == cutoff_score:
            result.append(item)
        else:
            break
    return result


# ============================================================
# 域详情回填（域码值/字典清单/命中缺失冲突明细）
# ============================================================

def _dict_pairs(business_rule: str) -> list[tuple[str, str]]:
    """解析字典"业务规则"列的枚举值定义：码-值;码-值;..."""
    return parse_enum_values(business_rule)


def build_item_details(pairs: list[tuple[str, str]], item_info: dict) -> dict:
    """构建一个枚举值项的候选明细：命中/缺失/码冲突。

    Args:
        pairs: 字段的 n 条 (码, 值)
        item_info: {"score": int, "matched": [...], "item_pairs": [(码,值)...域内码值]}

    Returns:
        {"matched_values": [...], "missing_values": [...], "conflict_values": [...]}
    """
    item_pair_map = {c: v for c, v in item_info.get("item_pairs", [])}
    matched_set = {v for _, v in item_info.get("matched", [])}

    matched_values, missing_values, conflict_values = [], [], []
    for code, value in pairs:
        if value in matched_set:
            matched_values.append(f"{code}-{value}")
        elif code in item_pair_map and item_pair_map[code] != value:
            # 该码在域中已被占用但值不同 → 码冲突（不可补充）
            conflict_values.append(f"{code}-{value}(域中该码为{item_pair_map[code]})")
        else:
            missing_values.append(f"{code}-{value}")
    return {
        "matched_values": matched_values,
        "missing_values": missing_values,
        "conflict_values": conflict_values,
    }


# ============================================================
# 降级检索（A 方案：搜集合内的名称条目）
# ============================================================

def search_by_name(field_name: str, top_k: int = 5) -> list[dict]:
    """枚举值匹配零候选时的降级检索：用字段名搜名称条目。

    Returns:
        [{"item_id": 标准编号, "name": 标准中文名称, "score": float}, ...]
    """
    if not field_name:
        return []

    client = get_client()
    ensure_loaded(client, ENUM_VALUE_COLLECTION)

    query_vec = embed_texts([field_name], is_query=True)[0]
    results = client.search(
        collection_name=ENUM_VALUE_COLLECTION,
        data=[query_vec],
        anns_field="value_dense",
        limit=top_k * 20,  # 名称条目占比小，扩大检索量
        output_fields=["item_id", "item_type", "value_text"],
        filter='item_type == "name"',
    )

    hits = []
    for hit in results[0]:
        hits.append({
            "item_id": hit["entity"]["item_id"],
            "name": hit["entity"]["value_text"],
            "score": hit["distance"],
        })
    return hits[:top_k]
