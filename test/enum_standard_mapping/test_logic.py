# -*- coding: utf-8 -*-
"""enum_standard_mapping 单元测试 -- stub 向量检索，不依赖 Milvus/LLM。

运行（项目根目录）：
  python -m pytest test/enum_standard_mapping/test_logic.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import enum_standard_mapping.domain_store as ds


# ============================================================
# stub：mock _batch_search_values
# ============================================================

def _stub_hits(hits_by_value):
    """构造打分 stub：hits_by_value = {值文本: [item_id...]}"""
    def fake(texts):
        return {
            text: [{"item_id": iid, "item_type": "domain", "score": 0.95} for iid in ids]
            for text, ids in hits_by_value.items() if text in texts
        }
    return fake


def _patch(monkeypatch, hits_by_value):
    monkeypatch.setattr(ds, "_batch_search_values", _stub_hits(hits_by_value))


# ============================================================
# 解析测试
# ============================================================

def test_parse_enum_values():
    pairs = ds.parse_enum_values("1-男;2-女;0-未知")
    assert pairs == [("1", "男"), ("2", "女"), ("0", "未知")]


def test_parse_enum_values_empty():
    assert ds.parse_enum_values("") == []
    assert ds.parse_enum_values(None) == []


def test_parse_enum_values_no_dash():
    pairs = ds.parse_enum_values("男;女")
    assert pairs == [("", "男"), ("", "女")]


# ============================================================
# 打分 + 淘汰测试
# ============================================================

def test_score_and_eliminate(monkeypatch):
    """3/4 命中的域存活，1/4 命中的域出局。"""
    # 字段: 1-男, 2-女, 0-未知, 9-其他
    pairs = [("1", "男"), ("2", "女"), ("0", "未知"), ("9", "其他")]
    _patch(monkeypatch, {
        "男": ["CDE00002"],   # 性别域
        "女": ["CDE00002"],
        "未知": ["CDE00002"],
        # "其他" 无命中
    })

    result = ds.score_enum_items(pairs)
    scores = result["item_scores"]
    assert scores["CDE00002"]["score"] == 3
    assert result["value_unmatched"] == ["其他"]

    # n=4: 存活线 = floor(4/2)+1 = 3
    ranked = ds.eliminate_and_rank(scores, 4)
    assert [r["item_id"] for r in ranked] == ["CDE00002"]
    assert ranked[0]["score"] == 3


def test_eliminate_below_half(monkeypatch):
    """n=4 命中2条（未命中2 >= ceil(4/2)=2）应出局。"""
    pairs = [("1", "a"), ("2", "b"), ("3", "c"), ("4", "d")]
    _patch(monkeypatch, {"a": ["CDE1"], "b": ["CDE1"]})
    result = ds.score_enum_items(pairs)
    ranked = ds.eliminate_and_rank(result["item_scores"], 4)
    assert ranked == []  # 2分 <= floor(4/2)=2 出局


def test_n3_two_hits_survive(monkeypatch):
    """n=3 命中2条存活（未命中1 < ceil(3/2)=2）。"""
    pairs = [("1", "a"), ("2", "b"), ("3", "c")]
    _patch(monkeypatch, {"a": ["CDE1"], "b": ["CDE1"]})
    result = ds.score_enum_items(pairs)
    ranked = ds.eliminate_and_rank(result["item_scores"], 3)
    assert len(ranked) == 1 and ranked[0]["score"] == 2


def test_full_score_dominates(monkeypatch):
    """满分项排最前。"""
    pairs = [("1", "a"), ("2", "b")]
    _patch(monkeypatch, {"a": ["CDE1", "CDE2"], "b": ["CDE1"]})
    result = ds.score_enum_items(pairs)
    ranked = ds.eliminate_and_rank(result["item_scores"], 2)
    assert ranked[0]["item_id"] == "CDE1" and ranked[0]["score"] == 2


# ============================================================
# Top20 含并列测试
# ============================================================

def test_top_n_with_ties():
    ranked = [
        {"item_id": f"CDE{i:03d}", "score": 10 - i // 3} for i in range(10)
    ]
    # 得分分布: 3项10分, 3项9分, 3项8分, 1项7分（i=9）
    top = ds.top_n_with_ties(ranked, 5)
    # 第5名是9分，并列的3个9分项都保留（3个10分+3个9分=6项）
    assert len(top) == 6
    assert all(t["score"] >= 9 for t in top)


def test_top_n_no_ties():
    ranked = [{"item_id": f"C{i}", "score": 10 - i} for i in range(5)]
    top = ds.top_n_with_ties(ranked, 3)
    assert len(top) == 3


# ============================================================
# 码冲突明细测试
# ============================================================

def test_build_item_details_conflict():
    """码相同值不同 → 码冲突。"""
    pairs = [("1", "柜面"), ("2", "手机银行")]
    # 域: 1-新柜面, 2-手机银行
    item_info = {
        "score": 1,
        "matched": [("2", "手机银行")],
        "item_pairs": [("1", "新柜面"), ("2", "手机银行")],
    }
    d = ds.build_item_details(pairs, item_info)
    assert d["matched_values"] == ["2-手机银行"]
    assert d["conflict_values"] == ["1-柜面(域中该码为新柜面)"]
    assert d["missing_values"] == []


def test_build_item_details_missing():
    """码不冲突的缺失值 → 可补充。"""
    pairs = [("1", "柜面"), ("9", "小程序")]
    item_info = {
        "score": 1,
        "matched": [("1", "柜面")],
        "item_pairs": [("1", "柜面"), ("2", "网上银行")],
    }
    d = ds.build_item_details(pairs, item_info)
    assert d["matched_values"] == ["1-柜面"]
    assert d["missing_values"] == ["9-小程序"]
    assert d["conflict_values"] == []
