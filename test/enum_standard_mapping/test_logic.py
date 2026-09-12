# -*- coding: utf-8 -*-
"""enum_standard_mapping 单元测试 -- stub 向量检索，不依赖 Milvus/LLM。

运行（项目根目录）：
  python -m pytest test/enum_standard_mapping/test_logic.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import enum_standard_mapping.enum_store as es


# ============================================================
# stub：mock _batch_search_values
# ============================================================

def _stub_hits(hits_by_value):
    """构造打分 stub：hits_by_value = {值文本: [(item_id, 枚举代码value_text, score)...]}"""
    def fake(texts):
        return {
            text: [{"item_id": iid, "value_text": v, "score": s} for iid, v, s in hits]
            for text, hits in hits_by_value.items() if text in texts
        }
    return fake


def _patch(monkeypatch, hits_by_value):
    monkeypatch.setattr(es, "_batch_search_values", _stub_hits(hits_by_value))


# ============================================================
# 解析测试
# ============================================================

def test_parse_enum_values():
    pairs = es.parse_enum_values("1-男;2-女;0-未知")
    assert pairs == [("1", "男"), ("2", "女"), ("0", "未知")]


def test_parse_enum_values_empty():
    assert es.parse_enum_values("") == []
    assert es.parse_enum_values(None) == []


def test_parse_enum_values_no_dash():
    pairs = es.parse_enum_values("男;女")
    assert pairs == [("", "男"), ("", "女")]


# ============================================================
# 枚举码有效性校验测试
# ============================================================

def test_is_valid_enum_code():
    assert es.is_valid_enum_code("1")
    assert es.is_valid_enum_code("01")
    assert es.is_valid_enum_code("CNY")
    assert es.is_valid_enum_code("ZXZQ_FJCPZB_FJDWJZ")
    assert es.is_valid_enum_code("BY DEFERRED PAYMENT")
    # 行标国标引用文本误解析出的伪码 → 无效
    assert not es.is_valid_enum_code("遵循《GB/T 12406")
    assert not es.is_valid_enum_code("参考《GBT4754")
    assert not es.is_valid_enum_code("本标准引用《GB/T2659 世界各国和地区名称代码》(等效于ISO3166")
    assert not es.is_valid_enum_code("遵循GB/T 12406")
    # 空码 → 无效（库内码值对必须有码）
    assert not es.is_valid_enum_code("")
    # 值含书名号 → 无效
    assert not es.is_valid_enum_code("1", "送审文件不属于《规章制度基本管理办法》所适用的制度")


def test_parse_valid_enum_pairs():
    """读取时刻过滤：正常码值对保留，伪码/无码/含书名号的对剔除。"""
    assert es.parse_valid_enum_pairs("1-男;2-女") == [("1", "男"), ("2", "女")]
    # 无码项（"男;女"）被剔除
    assert es.parse_valid_enum_pairs("男;女") == []
    # 行标国标引用文本误解析出的伪码被剔除
    assert es.parse_valid_enum_pairs("遵循《GB/T 12406-2008 表示货币和资金的代码》") == []
    # 值含书名号的该对剔除、其余保留
    assert es.parse_valid_enum_pairs(
        "1-送审文件不属于《规章制度基本管理办法》所适用的制度;2-缺少送审材料"
    ) == [("2", "缺少送审材料")]


# ============================================================
# 打分测试（单枚举值对单枚举代码最多 +1 + 一一占用）
# ============================================================

def test_score_dedup_same_enum_code(monkeypatch):
    """字段枚举值 A 命中同一枚举代码的多条 value（C、D），只 +1。"""
    pairs = [("1", "A"), ("2", "B")]
    _patch(monkeypatch, {
        "A": [("ENM001", "C", 0.90), ("ENM001", "D", 0.85), ("ENM002", "X", 0.95)],
        "B": [("ENM001", "E", 0.88)],
    })
    result = es.score_enum_items(pairs)
    scores = result["item_scores"]
    assert scores["ENM001"]["score"] == 2   # A +1（C、D 只算1），B +1（E）
    assert scores["ENM002"]["score"] == 1
    assert result["value_unmatched"] == []


def test_score_one_to_one_value_used(monkeypatch):
    """枚举代码只有一条 value C，A、B 都命中 C：C 被 A 占用后 B 不能再得分。"""
    pairs = [("1", "A"), ("2", "B")]
    _patch(monkeypatch, {
        "A": [("ENM001", "C", 0.90)],
        "B": [("ENM001", "C", 0.85)],
    })
    result = es.score_enum_items(pairs)
    assert result["item_scores"]["ENM001"]["score"] == 1
    assert result["item_scores"]["ENM001"]["matched"] == [("1", "A")]


def test_score_used_value_excluded(monkeypatch):
    """用户示例：字段 1-A;2-B，枚举代码值 C;D;E。
    A 命中 C（最高分）与 D → 只 +1 且占用 C；B 轮询时 C 已用，仅 D、E 可贡献。"""
    pairs = [("1", "A"), ("2", "B")]
    _patch(monkeypatch, {
        "A": [("ENM001", "C", 0.92), ("ENM001", "D", 0.85)],
        "B": [("ENM001", "C", 0.87), ("ENM001", "D", 0.90), ("ENM001", "E", 0.86)],
    })
    result = es.score_enum_items(pairs)
    assert result["item_scores"]["ENM001"]["score"] == 2   # A→C，B→D
    assert result["item_scores"]["ENM001"]["matched"] == [("1", "A"), ("2", "B")]


def test_score_enum_items(monkeypatch):
    """3/4 命中的枚举代码。"""
    pairs = [("1", "男"), ("2", "女"), ("0", "未知"), ("9", "其他")]
    _patch(monkeypatch, {
        "男": [("ENM00002", "男", 0.95)],
        "女": [("ENM00002", "女", 0.95)],
        "未知": [("ENM00002", "未知", 0.95)],
        # "其他" 无命中
    })
    result = es.score_enum_items(pairs)
    scores = result["item_scores"]
    assert scores["ENM00002"]["score"] == 3
    assert result["value_unmatched"] == ["其他"]


# ============================================================
# 召回筛选测试
# ============================================================

def test_filter_recall_threshold_and_operation():
    """n=4: 存活线 floor(4/2)+1=3；score==4 判复用，3 判修改。"""
    item_scores = {
        "ENM001": {"score": 3, "matched": []},
        "ENM002": {"score": 4, "matched": []},
        "ENM003": {"score": 2, "matched": []},
    }
    rec = es.filter_recall_standards(item_scores, 4)
    assert [r["item_id"] for r in rec] == ["ENM002", "ENM001"]
    assert rec[0]["operation"] == "复用"
    assert rec[1]["operation"] == "修改"


def test_filter_recall_below_half_eliminated():
    """n=4 命中2条（未命中2 >= ceil(4/2)=2）应出局。"""
    item_scores = {"ENM001": {"score": 2, "matched": []}}
    rec = es.filter_recall_standards(item_scores, 4)
    assert rec == []  # 2分 < floor(4/2)+1=3 出局 → 需新增


def test_filter_recall_top_n():
    """按 score 降序取前 2 个。"""
    item_scores = {
        "ENM001": {"score": 5, "matched": []},
        "ENM002": {"score": 4, "matched": []},
        "ENM003": {"score": 4, "matched": []},
        "ENM004": {"score": 3, "matched": []},
    }
    rec = es.filter_recall_standards(item_scores, 5, top_n=2)
    assert [r["item_id"] for r in rec] == ["ENM001", "ENM002"]


def test_filter_recall_full_score_reuse():
    """score == n → 复用。"""
    item_scores = {"ENM001": {"score": 2, "matched": []}}
    rec = es.filter_recall_standards(item_scores, 2)
    assert len(rec) == 1 and rec[0]["operation"] == "复用"


def test_filter_recall_n0_empty():
    assert es.filter_recall_standards({}, 0) == []


# ============================================================
# 命中/缺失明细测试（只看码值，不比较码）
# ============================================================

def test_build_item_details_missing():
    """未命中的字段码值 → 缺失（可补充）。"""
    pairs = [("1", "柜面"), ("9", "小程序")]
    item_info = {"matched": [("1", "柜面")]}
    d = es.build_item_details(pairs, item_info)
    assert d["matched_values"] == ["1-柜面"]
    assert d["missing_values"] == ["9-小程序"]
    assert "conflict_values" not in d


def test_build_item_details_value_based_no_code_conflict():
    """码相同值不同不再视为冲突：未命中的字段值一律归为缺失。"""
    pairs = [("1", "柜面"), ("2", "手机银行")]
    item_info = {"matched": [("2", "手机银行")]}
    d = es.build_item_details(pairs, item_info)
    assert d["matched_values"] == ["2-手机银行"]
    assert d["missing_values"] == ["1-柜面"]
    assert "conflict_values" not in d
