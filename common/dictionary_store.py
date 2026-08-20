# -*- coding: utf-8 -*-

"""存量字典查询模块 -- 懒加载全量字典 Excel，按标准编号索引。

提供根据标准编号列表批量查询字典完整信息的能力，
用于在标准落标流程中，将向量检索返回的标准编号回填为完整的候选标准对象。
"""

import os
import threading
import logging

import pandas as pd

from config import DICTIONARY_PATH

_logger = logging.getLogger(__name__)

_df_lock = threading.Lock()
_df = None


# ============================================================
# 内部工具
# ============================================================

def _load():
    """懒加载全量字典 Excel，以标准编号为索引。"""
    global _df
    if _df is not None:
        return _df

    with _df_lock:
        if _df is not None:
            return _df

        if not os.path.exists(DICTIONARY_PATH):
            raise FileNotFoundError(f"全量字典文件不存在: {DICTIONARY_PATH}")

        _logger.info("加载全量字典: %s", DICTIONARY_PATH)
        df = pd.read_excel(DICTIONARY_PATH, sheet_name="全量字典", dtype=str)

        dup = df[df.duplicated(subset=["标准编号"], keep=False)]
        if not dup.empty:
            _logger.warning("发现 %d 条重复标准编号，将保留最后一条", len(dup))

        df = df.drop_duplicates(subset=["标准编号"], keep="last")
        df = df.set_index("标准编号")
        # 标准中文名称归一化列（精确同名保底查询用）
        df["_name_key"] = df["标准中文名称"].astype(str).str.strip()
        _df = df
        _logger.info("全量字典加载完成: %d 条", len(df))

    return _df


def _row_to_dict(std_id, row):
    """将 DataFrame 行转为 CandidateStandard 兼容的字典。"""
    return {
        "std_id": std_id,
        "std_name": str(row.get("标准中文名称", "")),
        "std_type": str(row.get("标准所属类型", "")),
        "business_definition": str(row.get("业务定义", "")),
        "domain_id": str(row.get("域编号", "")),
        "domain_name": str(row.get("域名称", "")),
        "domain_type": str(row.get("域类型", "")),
        "data_example": "",
    }


# ============================================================
# 对外接口
# ============================================================

def get_by_id(std_id):
    """根据标准编号查询单条字典信息。"""
    df = _load()
    if std_id not in df.index:
        return None
    return _row_to_dict(std_id, df.loc[std_id])


def get_by_ids(std_ids):
    """根据标准编号列表批量查询字典信息，保持输入顺序。"""
    df = _load()
    results = []
    missing = []

    for sid in std_ids:
        if sid in df.index:
            results.append(_row_to_dict(sid, df.loc[sid]))
        else:
            missing.append(sid)

    if missing:
        _logger.warning("以下标准编号在字典中不存在，已跳过: %s", missing)

    return results


def get_by_name(std_name, field_type=None):
    """按标准中文名称精确匹配查询（可选限定标准所属类型）。

    名称去除首尾空白后全等匹配，用于检索未命中时的精确同名保底。
    返回列表（可能存在多个同名标准）。
    """
    df = _load()
    name = str(std_name).strip()
    if not name:
        return []

    mask = df["_name_key"] == name
    if field_type:
        mask &= df["标准所属类型"].astype(str) == field_type

    matches = df[mask]
    return [_row_to_dict(sid, row) for sid, row in matches.iterrows()]
