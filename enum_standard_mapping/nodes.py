# -*- coding: utf-8 -*-
"""枚举落标 LangGraph 节点定义。

图结构：
  START
    ↓
  load_and_score  -- 读取 Excel，筛选代码枚举类字段，解析枚举值，向量打分 + 召回筛选（Top5）
    ↓
  select_result   -- 第4步 LLM 标准判定（复用 standard_mapping 逻辑）+ 与第3步枚举代码操作合并为五分类结果
    ↓
  write_result    -- 输出结果 Excel
    ↓
  END
"""

import logging

from enum_standard_mapping.state import EnumMappingGraphState, FieldToMap, EnumItemDetail
from enum_standard_mapping.excel_utils import read_excel, write_excel
from enum_standard_mapping.enum_store import (
    parse_valid_enum_pairs,
    score_enum_items,
    filter_recall_standards,
    build_item_details,
)
from enum_standard_mapping.constants import (
    ENUM_FIELD_TYPE,
    RESULT_NEW,
    RESULT_REUSE_REUSE,
    RESULT_REUSE_MODIFY,
    RESULT_MODIFY_REUSE,
    RESULT_MODIFY_MODIFY,
    OP_REUSE,
)
from config import (
    ENUM_RECALL_TOP_N,
    ENUM_VALUE_COLLECTION,
)
from common.vector_store import get_client, ensure_loaded, translate_milvus_error
from common.exceptions import NonRetryableError
from common.llm_client import build_row_result_map
from common.dictionary_store import _load as _load_dict_df

_logger = logging.getLogger(__name__)


# ============================================================
# 枚举代码详情回填（码值对 + 引用标准清单）
# ============================================================

def _get_item_pairs_and_standards(item_id: str) -> tuple[list[tuple[str, str]], list[dict], str]:
    """从全量字典按枚举值编号回填枚举代码的码值对、引用标准清单和标准名。

    Returns:
        (item_pairs, standards, item_name)
        standards: [{"std_id", "std_name", "business_definition"}, ...]
    """
    df = _load_dict_df()
    sub = df[df["枚举值编号"] == item_id]
    if sub.empty:
        return [], [], ""
    item_name = str(sub.iloc[0].get("标准中文名称", "") or "")
    standards = [{
        "std_id": sid,
        "std_name": str(row.get("标准中文名称", "")),
        "business_definition": str(row.get("业务定义", "")),
    } for sid, row in sub.iterrows()]
    # 码值取第一个非空业务规则（同枚举代码下码值一致）；读取时即筛除无效码值对，
    # 无有效码值对视为该枚举代码不存在（与 scripts 入库逻辑一致）
    for _, row in sub.iterrows():
        rule = str(row.get("业务规则", "") or "")
        pairs = parse_valid_enum_pairs(rule)
        if pairs:
            return pairs, standards, item_name
    return [], [], ""


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
        print(f"  筛选: 排除 {skipped} 行非代码枚举类字段")
    if not rows:
        print("  无代码枚举类字段，处理结束")
        return {"rows": rows, "selection_results": []}

    # 加载阶段筛除无效枚举值字段：解析不出有效码值对（引用文本/无码等）视为不可用，直接从 rows 剔除
    valid_rows = []
    invalid = 0
    for row in rows:
        pairs = parse_valid_enum_pairs(row["enum_values"])
        if not pairs:
            invalid += 1
            continue
        row["pairs"] = pairs
        valid_rows.append(row)
    rows = valid_rows
    if invalid:
        print(f"  加载筛除: {invalid} 行枚举值无效（无有效码值对），已从处理列表剔除")

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
    """对单行字段执行打分 + 召回筛选（Top5）+ 明细回填。

    前置条件：row["pairs"] 已由 load_and_score_node 在加载阶段筛除无效枚举值且非空；
    本函数只负责打分与召回。
    """
    pairs = row["pairs"]
    n = len(pairs)

    result = score_enum_items(pairs)
    rec = filter_recall_standards(result["item_scores"], n, ENUM_RECALL_TOP_N)

    candidates = []
    for item in rec:
        item_id = item["item_id"]
        item_pairs, standards, item_name = _get_item_pairs_and_standards(item_id)
        if not item_pairs:
            continue
        details = build_item_details(pairs, {
            "matched": item["matched"],
        })
        candidates.append(EnumItemDetail(
            item_id=item_id,
            item_name=item_name,
            standards=standards,
            score=item["score"],
            operation=item["operation"],
            matched_values=details["matched_values"],
            missing_values=details["missing_values"],
        ))
    row["candidates"] = candidates


# ============================================================
# 节点 2: LLM 标准判定 + 结果合并
# ============================================================

def select_result_node(state: EnumMappingGraphState) -> dict:
    """调用 LLM 判定标准（复用 standard_mapping 逻辑）。

    - 检索失败的行标记"候选检索失败，需人工复核"
    - 召回为空（无候选枚举代码）的行直接判"新增枚举代码新增标准"
    - 其余行交 LLM 判定，再合并为五分类结果
    """
    print("\n=== 步骤 2/3: LLM 标准判定与结果合并 ===")
    rows = state["rows"]

    rows_to_select = []
    direct_result_count = 0

    for row in rows:
        if row.get("candidate_fetch_error"):
            row["mapping_result"] = "候选检索失败，需人工复核"
            row["llm_reason"] = row["candidate_fetch_error"]
            direct_result_count += 1
        elif not row["candidates"]:
            # 枚举代码召回无候选 → 新增枚举代码新增标准
            row["mapping_result"] = RESULT_NEW
            row["llm_reason"] = "枚举值召回无候选枚举代码，判定新增枚举代码并新增标准"
            direct_result_count += 1
        else:
            rows_to_select.append(_build_llm_input(row))

    if direct_result_count:
        print(f"  {direct_result_count} 行直接判定（检索失败/召回无候选）")

    if not rows_to_select:
        print("  没有需要 LLM 判定的行")
        return {"rows": rows, "selection_results": []}

    print(f"  共 {len(rows_to_select)} 行需要 LLM 判定")
    from common.llm_client import get_llm
    from standard_mapping.llm import select_standard
    llm = get_llm()
    try:
        results = select_standard(llm, rows_to_select, log_module="enum_standard_mapping")
    except Exception as e:
        # LLM 失败兜底：相关行标记失败，保留候选明细供人工处理
        pending = {r["row_index"] for r in rows_to_select}
        for row in rows:
            if row["index"] in pending:
                row["mapping_result"] = "LLM判断失败"
                row["llm_reason"] = f"LLM 调用失败（重试后仍失败）: {e}"
        print(f"  LLM 判定失败: {e}")
        return {"rows": rows, "selection_results": []}

    # 应用 LLM 结果并合并第 3 步操作
    selection_results = []
    result_map, duplicate_indices = build_row_result_map(results)
    sent_indices = {r["row_index"] for r in rows_to_select}
    missing_count = 0
    for row in rows:
        idx = row["index"]
        if idx in duplicate_indices:
            row["mapping_result"] = "LLM返回重复结果，需人工复核"
            row["llm_reason"] = "LLM 调用成功但同一 row_index 返回多条结果，需人工复核"
            continue
        if idx not in result_map:
            if idx in sent_indices:
                row["mapping_result"] = "LLM未返回该行结果，需人工复核"
                row["llm_reason"] = "LLM 调用成功但返回结果中缺少该行，需人工复核"
                missing_count += 1
            continue
        r = result_map[idx]
        _apply_llm_result(row, r)
        selection_results.append(r)

    if missing_count:
        print(f"  [WARNING] LLM 返回结果缺少 {missing_count} 行，已标记需人工复核")
    print(f"  标准判定完成，共 {len(selection_results)} 条结果")
    return {"rows": rows, "selection_results": selection_results}


def _apply_llm_result(row: FieldToMap, r: dict) -> None:
    """将单行 LLM 判定结果与第 3 步枚举代码操作合并为五分类结果。"""
    selection = r["selection"]
    if selection == "新增标准":
        row["mapping_result"] = RESULT_NEW
        row["llm_reason"] = r["reason"]
        return

    # 定位选中标准所属的枚举代码候选
    sel_cand = None
    for c in row["candidates"]:
        if any(s["std_id"] == r["selected_std_id"] for s in c["standards"]):
            sel_cand = c
            break
    if sel_cand is None:
        row["mapping_result"] = "LLM返回异常结果，需人工复核"
        row["llm_reason"] = f"LLM 选中的标准编号 {r['selected_std_id']} 不在召回候选内，需人工复核"
        return

    op = sel_cand["operation"]
    if selection == "复用已有标准":
        row["mapping_result"] = RESULT_REUSE_REUSE if op == OP_REUSE else RESULT_MODIFY_REUSE
    else:  # 复用已有标准但扩展业务定义（=修改已有标准）
        row["mapping_result"] = RESULT_REUSE_MODIFY if op == OP_REUSE else RESULT_MODIFY_MODIFY

    row["selected_std_id"] = r["selected_std_id"]
    row["selected_std_name"] = r["selected_std_name"]

    # 修改枚举代码：生成补充建议
    if op != OP_REUSE:
        row["enum_code_suggestion"] = _build_enum_code_suggestion(sel_cand)
    row["llm_reason"] = r["reason"]
    if r.get("extension_suggestion"):
        row["llm_reason"] += f" 扩展建议: {r['extension_suggestion']}"


def _build_enum_code_suggestion(cand: EnumItemDetail) -> str:
    """生成修改枚举代码的补充建议：把字段中缺失的码值对补充进该枚举代码（只看码值，不看码）。"""
    enm = cand["item_id"]
    parts = []
    if cand["missing_values"]:
        parts.append(f"向枚举代码{enm}补充: {', '.join(cand['missing_values'])}")
    return "; ".join(parts)


def _build_llm_input(row: FieldToMap) -> dict:
    """构建单行 LLM 输入数据（仅标准名 + 业务定义，与 standard_mapping 一致）。"""
    candidates = []
    seen = set()
    for c in row["candidates"]:
        for s in c["standards"]:
            if s["std_id"] in seen:
                continue
            seen.add(s["std_id"])
            candidates.append({
                "std_id": s["std_id"],
                "std_name": s["std_name"],
                "business_definition": s.get("business_definition", ""),
            })
    return {
        "row_index": row["index"],
        "field_name": row["field_name"],
        "business_meaning": row["business_meaning"],
        "candidates": candidates,
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
