# -*- coding: utf-8 -*-
"""枚举值向量集合的检索与打分 -- 阶段 1 核心逻辑。

集合 dict_enum_values 的存储粒度是"枚举值项"，item_id 为枚举代码编号（ENMxxxxx），
每个枚举代码对应一组枚举值（码-值），供代码枚举类字段落标时向量召回。

打分规则（二值制 + 一一占用）：
  字段 n 条码值逐条向量检索，相似度 >= 阈值计"命中"；
  同一枚举代码对同一字段枚举值最多命中 1 次（+1）；
  枚举代码的每条 value 最多被一个字段枚举值占用：被占用（"用过"）的 value
  不再参与后续字段枚举值的匹配（例：字段 A、B，枚举代码含 C、D、E；
  A 命中 C（最高分）和 D → 只 +1 且占用 C；B 轮询时 C 已用，仅 D、E 可贡献）。

召回筛选：
  filter_recall_standards 按 score >= floor(n/2)+1 过滤，score 由大到小排列取前 top_n 个；
  score == n 判"复用"，score < n 判"修改"；返回空列表说明需"新增枚举代码新增标准"。
"""

import math
import logging
import re
from collections import defaultdict

from config import (
    ENUM_VALUE_COLLECTION,
    ENUM_VALUE_MATCH_THRESHOLD,
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
    "value_text",
]

# 行标国标引用文本特征（如"遵循《GB/T 12406-2008 ...》"被误拆出的伪码/残留值）。
# 码或值含书名号《》或 GB/T、GBT 引用特征的一律视为无效
_INVALID_REF_RE = re.compile(r"[《》]|GB/T|GBT")


def is_valid_enum_code(code: str, value: str = "") -> bool:
    """判断枚举值对是否有效：码非空，且码/值均不含行标国标引用文本特征。

    用于剔除 业务规则 中"参考《GB/T ...》"类文本被误解析出的伪码与残留引用文本的值
    （无效枚举定义，见 README：不允许编码规则形如"遵循《GB/T ...》"的枚举代码出现在标准库中）。
    """
    if not code:
        return False
    return not _INVALID_REF_RE.search(code) and not _INVALID_REF_RE.search(value)


def parse_valid_enum_pairs(enum_text: str) -> list[tuple[str, str]]:
    """解析枚举值文本并筛除无效码值对（读取时刻即过滤）。

    在 parse_enum_values 基础上剔除：无码项、行标国标引用文本误解析出的伪码，
    以及码或值含书名号/GB 引用特征的对。
    """
    return [(c, v) for c, v in parse_enum_values(enum_text) if is_valid_enum_code(c, v)]


# ============================================================
# 枚举值解析
# ============================================================

def parse_enum_values(enum_text: str) -> list[tuple[str, str]]:
    """解析规范化枚举值为 (码, 值) 列表。

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
# 枚举代码打分（阶段 1 核心）
# ============================================================

def _batch_search_values(value_texts: list[str]) -> dict[str, list[dict]]:
    """将字段 n 条码值文本批量向量检索，返回 {码值文本: [命中条目...]}。

    每条命中条目含 item_id / 命中的枚举代码值文本 value_text / 相似度得分。
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
    )

    hits_by_text = {}
    for text, hits in zip(value_texts, results):
        kept = []
        for hit in hits:
            score = hit["distance"]
            if score >= ENUM_VALUE_MATCH_THRESHOLD:
                kept.append({
                    "item_id": hit["entity"]["item_id"],
                    "value_text": hit["entity"]["value_text"],
                    "score": score,
                })
        if kept:
            hits_by_text[text] = kept
    return hits_by_text


def score_enum_items(pairs: list[tuple[str, str]]) -> dict:
    """对一个待落标字段的 n 条 (码, 值) 全库打分。

    规则（一一占用）：
      1. 每个字段枚举值独立检索；
      2. 对一个枚举代码，一个字段枚举值最多 +1（命中该枚举代码多条 value 也只计 1 分）；
      3. 枚举代码的每条 value 最多被一个字段枚举值占用：被占用（"用过"）的 value
         不再参与后续字段枚举值的匹配。

    Returns:
        {
          "hits_by_value": {值文本: [命中item...]},   # 阈值过滤后的检索结果
          "item_scores": {item_id: {"score": int, "matched": [(码,值)...]}},
          "value_unmatched": [值文本...],             # 全库未命中的字段码值
        }
    """
    value_texts = [v for _, v in pairs]
    hits_by_value = _batch_search_values(value_texts)

    # 按枚举代码聚合得分：每个字段枚举值对每个枚举代码只取一条"未占用"的最高分命中
    item_scores = defaultdict(lambda: {"score": 0, "matched": []})
    used_values = defaultdict(set)  # item_id -> 已被字段枚举值占用的枚举代码 value_text
    for code, value in pairs:
        hits = hits_by_value.get(value)
        if not hits:
            continue
        best_by_item = {}
        for h in hits:
            iid = h["item_id"]
            if h["value_text"] in used_values[iid]:
                continue
            if iid not in best_by_item or h["score"] > best_by_item[iid]["score"]:
                best_by_item[iid] = h
        for iid, h in best_by_item.items():
            item_scores[iid]["score"] += 1
            item_scores[iid]["matched"].append((code, value))
            used_values[iid].add(h["value_text"])

    unmatched = [v for _, v in pairs if v not in hits_by_value]
    return {
        "hits_by_value": hits_by_value,
        "item_scores": dict(item_scores),
        "value_unmatched": unmatched,
    }


def filter_recall_standards(item_scores: dict, n: int, top_n: int = 5) -> list[dict]:
    """筛选召回标准（阶段 1 出候选）。

    规则：
      1. 筛除 score 未到 floor(n/2)+1 的枚举代码
      2. 按 score 由大到小排列（同分按 item_id 稳定排序），取前 top_n 个
      3. 每条输出 {"item_id", "score", "matched", "operation"}：
           score == n  -> "复用"
           score <  n  -> "修改"
      4. 返回空列表说明需"新增枚举代码新增标准"

    n=0 时返回空。
    """
    if n <= 0:
        return []
    min_score = math.floor(n / 2) + 1  # 存活线：score >= floor(n/2)+1
    survivors = [
        {
            "item_id": item_id,
            "score": info["score"],
            "matched": info["matched"],
            "operation": "复用" if info["score"] == n else "修改",
        }
        for item_id, info in item_scores.items()
        if info["score"] >= min_score
    ]
    survivors.sort(key=lambda x: (-x["score"], x["item_id"]))
    return survivors[:top_n]


def build_item_details(pairs: list[tuple[str, str]], item_info: dict) -> dict:
    """构建一个枚举代码的候选明细：命中/缺失（仅按码值文本，不比较码）。

    Args:
        pairs: 字段的 n 条 (码, 值)
        item_info: {"matched": [(码,值)...字段命中该枚举代码的码值]}

    Returns:
        {"matched_values": [...], "missing_values": [...]}
        未命中的字段码值一律归为缺失（可补充进枚举代码），码是否与枚举代码内已有码重复不重要。
    """
    matched_set = {v for _, v in item_info.get("matched", [])}
    matched_values, missing_values = [], []
    for code, value in pairs:
        if value in matched_set:
            matched_values.append(f"{code}-{value}")
        else:
            missing_values.append(f"{code}-{value}")
    return {
        "matched_values": matched_values,
        "missing_values": missing_values,
    }
