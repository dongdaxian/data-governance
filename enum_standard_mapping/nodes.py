# -*- coding: utf-8 -*-
"""枚举落标 LangGraph 节点定义。

图结构：
  START
    ↓
  load_and_score  -- 读取 Excel，筛选代码枚举类字段，解析枚举值，向量打分 + 淘汰 + Top20 + 明细回填
    ↓
  select_result   -- LLM 七分类判定（含零候选降级）
    ↓
  write_result    -- 输出结果 Excel
    ↓
  END
"""

import logging

from enum_standard_mapping.state import EnumMappingGraphState, FieldToMap, EnumItemDetail
from enum_standard_mapping.excel_utils import read_excel, write_excel
from enum_standard_mapping.domain_store import (
    parse_enum_values,
    score_enum_items,
    eliminate_and_rank,
    top_n_with_ties,
    build_item_details,
    search_by_name,
)
from enum_standard_mapping.constants import (
    ENUM_FIELD_TYPE,
    RESULT_3,
    RESULT_6,
)
from config import (
    ENUM_CANDIDATE_TOP_N,
    ENUM_VALUE_COLLECTION,
)
from common.vector_store import get_client, ensure_loaded, translate_milvus_error
from common.exceptions import NonRetryableError
from common.dictionary_store import _load as _load_dict_df

_logger = logging.getLogger(__name__)


# ============================================================
# 域详情回填（域码值对 + 字典清单）
# ============================================================

def _get_item_pairs_and_standards(item_id: str, item_type: str) -> tuple[list[tuple[str, str]], list[dict], str]:
    """从全量字典回填枚举值项的码值对、名下字典清单和项名称。

    Returns:
        (item_pairs, standards, item_name)
        有域项：按域编号聚合名下所有字典（码值取首个非空业务规则）
        无域项：该字典自身
    """
    df = _load_dict_df()
    if item_type == "standard":
        if item_id not in df.index:
            return [], [], ""
        row = df.loc[item_id]
        rule = str(row.get("业务规则", "") or "")
        pairs = parse_enum_values(rule)
        return pairs, [{
            "std_id": item_id,
            "std_name": str(row.get("标准中文名称", "")),
        }], str(row.get("标准中文名称", ""))

    # domain
    sub = df[df["域编号"] == item_id]
    if sub.empty:
        return [], [], ""
    item_name = str(sub.iloc[0].get("域名称", "") or "")
    standards = [{
        "std_id": sid,
        "std_name": str(row.get("标准中文名称", "")),
    } for sid, row in sub.iterrows()]
    # 码值取第一个非空业务规则（同域字典码值相同）
    pairs = []
    for _, row in sub.iterrows():
        rule = str(row.get("业务规则", "") or "")
        pairs = parse_enum_values(rule)
        if pairs:
            break
    return pairs, standards, item_name


# ============================================================
# 节点 1: 加载 Excel + 枚举值打分
# ============================================================

def load_and_score_node(state: EnumMappingGraphState) -> dict:
    """读取输入 Excel，筛选代码枚举类字段，解析枚举值并打分获取候选。"""
    print("\n=== 步骤 1/3: 加载 Excel 并枚举值打分 ===")
    all_rows = read_excel(state["input_file"])

    # 筛选代码枚举类字段
    rows = [r for r in all_rows if r["field_type"] == ENUM_FIELD_TYPE]
    skipped = len(all_rows) - len(rows)
    if skipped > 0:
        print(f"  筛选: 排除 {skipped} 行非代码枚举类字段，保留 {len(rows)} 行待落标")
    if not rows:
        print("  无代码枚举类字段，处理结束")
        return {"rows": rows, "selection_results": []}

    # 集合预热
    client = get_client()
    ensure_loaded(client, ENUM_VALUE_COLLECTION)

    consecutive_config_errors = 0
    for row in rows:
        try:
            _score_row(row)
            consecutive_config_errors = 0
        except Exception as e:
            row["candidates"] = []
            translated = translate_milvus_error(e)
            if isinstance(translated, NonRetryableError):
                consecutive_config_errors += 1
                row["candidate_fetch_error"] = f"配置/鉴权错误: {translated}"
                print(f"  行 {row['index']} 配置/鉴权错误（不重试）: {translated}")
                if consecutive_config_errors >= 3:
                    raise RuntimeError(
                        f"连续 {consecutive_config_errors} 行遇到不可重试错误，"
                        f"疑似配置问题（如 MILVUS_TOKEN 错误），已中止任务，请检查配置后重跑: {translated}"
                    ) from e
            else:
                row["candidate_fetch_error"] = f"候选检索失败: {e}"
                print(f"  行 {row['index']} 候选检索失败: {e}")

    print(f"  枚举值打分完成: {len(rows)} 行")
    return {"rows": rows, "selection_results": [], "include_candidates": state.get("include_candidates", False)}


def _score_row(row: FieldToMap) -> None:
    """对单行字段执行打分 + 淘汰 + Top20 + 明细回填。"""
    pairs = parse_enum_values(row["enum_values"])
    row["pairs"] = pairs
    n = len(pairs)
    if n == 0:
        row["candidates"] = []
        return

    result = score_enum_items(pairs)
    ranked = eliminate_and_rank(result["item_scores"], n)
    top = top_n_with_ties(ranked, ENUM_CANDIDATE_TOP_N)

    candidates = []
    for item in top:
        item_id = item["item_id"]
        item_type = item.get("item_type") or ("domain" if item_id.startswith("CDE") else "standard")
        item_pairs, standards, item_name = _get_item_pairs_and_standards(item_id, item_type)
        if not item_pairs:
            continue
        details = build_item_details(pairs, {
            "score": item["score"],
            "matched": item["matched"],
            "item_pairs": item_pairs,
        })
        candidates.append(EnumItemDetail(
            item_id=item_id,
            item_type=item_type,
            item_name=item_name,
            standards=standards,
            score=item["score"],
            matched_values=details["matched_values"],
            missing_values=details["missing_values"],
            conflict_values=details["conflict_values"],
            item_pairs=item_pairs,
        ))
    row["candidates"] = candidates

    # 零候选 → 降级名称检索
    if not candidates:
        row["degraded_name_hits"] = search_by_name(row["field_name"])
        print(f"  行 {row['index']} 枚举值零候选，降级名称检索命中 {len(row['degraded_name_hits'])} 条")


# ============================================================
# 节点 2: LLM 七分类判定
# ============================================================

def select_result_node(state: EnumMappingGraphState) -> dict:
    """调用 LLM 判定七分类结果。

    - 检索失败的行标记"候选检索失败，需人工复核"
    - 零候选且降级名称检索也miss的行直接判结果3
    - 其余行交 LLM 判定
    """
    print("\n=== 步骤 2/3: LLM 七分类判定 ===")
    rows = state["rows"]

    rows_to_select = []
    direct_result_count = 0

    for row in rows:
        if row.get("candidate_fetch_error"):
            row["mapping_result"] = "候选检索失败，需人工复核"
            row["llm_reason"] = row["candidate_fetch_error"]
            direct_result_count += 1
        elif not row["candidates"] and not row.get("degraded_name_hits"):
            # 码值零候选且名称也不命中 → 结果3
            row["mapping_result"] = RESULT_3
            row["llm_reason"] = "枚举值匹配零候选且名称检索无命中，判定新增域并新增标准"
            direct_result_count += 1
        else:
            rows_to_select.append(_build_llm_input(row))

    if direct_result_count:
        print(f"  {direct_result_count} 行直接判定（检索失败/零候选）")

    if not rows_to_select:
        print("  没有需要 LLM 判定的行")
        return {"rows": rows, "selection_results": []}

    print(f"  共 {len(rows_to_select)} 行需要 LLM 判定")
    from common.llm_client import get_llm
    from enum_standard_mapping.llm import select_enum_result
    llm = get_llm()
    try:
        results = select_enum_result(llm, rows_to_select)
    except Exception as e:
        # LLM 失败兜底：相关行标记失败，保留候选明细供人工处理
        pending = {r["row_index"] for r in rows_to_select}
        for row in rows:
            if row["index"] in pending:
                row["mapping_result"] = "LLM判断失败"
                row["llm_reason"] = f"LLM 调用失败（重试后仍失败）: {e}"
        print(f"  LLM 判定失败: {e}")
        return {"rows": rows, "selection_results": []}

    # 应用 LLM 结果
    selection_results = []
    result_map = {r["row_index"]: r for r in results}
    sent_indices = {r["row_index"] for r in rows_to_select}
    missing_count = 0
    for row in rows:
        idx = row["index"]
        if idx not in result_map:
            if idx in sent_indices:
                row["mapping_result"] = "LLM未返回该行结果，需人工复核"
                row["llm_reason"] = "LLM 调用成功但返回结果中缺少该行，需人工复核"
                missing_count += 1
            continue
        r = result_map[idx]
        row["mapping_result"] = r["selection"]
        row["selected_std_id"] = r["selected_std_id"]
        row["selected_std_name"] = r["selected_std_name"]
        row["domain_action"] = r["domain_action"]
        row["conflict_detail"] = r["conflict_detail"]
        row["llm_reason"] = r["reason"]
        selection_results.append(r)

    if missing_count:
        print(f"  [WARNING] LLM 返回结果缺少 {missing_count} 行，已标记需人工复核")
    print(f"  七分类判定完成，共 {len(selection_results)} 条结果")
    return {"rows": rows, "selection_results": selection_results}


def _build_llm_input(row: FieldToMap) -> dict:
    """构建单行 LLM 输入数据。"""
    return {
        "row_index": row["index"],
        "field_name": row["field_name"],
        "business_meaning": row["business_meaning"],
        "enum_values": row["enum_values"],
        "candidates": [
            {
                "item_id": c["item_id"],
                "item_type": c["item_type"],
                "item_name": c["item_name"],
                "score": c["score"],
                "matched_values": c["matched_values"],
                "missing_values": c["missing_values"],
                "conflict_values": c["conflict_values"],
                "item_pairs": [f"{code}-{value}" for code, value in c["item_pairs"]],
                "standards": [f"{s['std_id']}:{s['std_name']}" for s in c["standards"]],
            }
            for c in row["candidates"]
        ],
        "degraded_name_hits": row.get("degraded_name_hits") or [],
    }


# ============================================================
# 节点 3: 写入结果 Excel
# ============================================================

def write_result_node(state: EnumMappingGraphState) -> dict:
    """将枚举落标结果写入输出 Excel。"""
    print("\n=== 步骤 3/3: 写入结果 Excel ===")
    write_excel(
        state["output_file"],
        state["rows"],
        state["input_file"],
        include_candidates=state.get("include_candidates", False),
    )
    return {}
