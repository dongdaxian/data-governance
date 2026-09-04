"""落标处理 LangGraph 节点定义。

图结构：
  START
    ↓
  load_and_fetch   -- 读取 Excel，筛选非枚举类字段，向量检索 + 字典回填获取备选标准
    ↓
  check_domain     -- 域类型精筛（标志类恒定通过，非标志类正则检测冲突，冲突则淘汰）
    ↓
  select_standard  -- LLM 标准选择（复用/复用扩展/新增）
    ↓
  write_result     -- 输出结果 Excel
    ↓
  END
"""

from standard_mapping.state import MappingGraphState, FieldToMap, CandidateStandard
from standard_mapping.excel_utils import read_excel, write_excel
from standard_mapping.llm import get_llm, select_standard
from standard_mapping.constants import NON_ENUM_TYPES
from common.domain_rules import check_data_example
from common.vector_store import search as vector_search
from common.dictionary_store import (
    get_by_ids as get_standards_by_ids,
    get_by_name as get_standards_by_name,
)


# ============================================================
# 备选标准获取（向量检索 + 字典回填）
# ============================================================

def fetch_candidates(field_name: str, business_meaning: str, field_type: str) -> list[CandidateStandard]:
    """向量检索 + 字典回填，获取备选标准列表。

    流程:
      1. 调用向量检索（稠密 top10 + 稀疏 top10 -> 合并去重）
      2. 根据返回的标准编号，从存量字典补全完整信息
      3. 精确同名保底：字典中存在与字段名完全一致的标准时并入候选（置顶）

    Args:
        field_name: 字段中文名
        business_meaning: 业务含义
        field_type: 字段所属类型

    Returns:
        备选标准列表，每项包含 std_id/std_name/std_type/business_definition/
        domain_id/domain_name/domain_type/data_example
    """
    # 1. 向量检索
    search_results = vector_search(
        query_name=field_name,
        query_meaning=business_meaning,
        top_k=10,
        field_type=field_type,
    )

    if not search_results:
        return _ensure_exact_name_match([], field_name, field_type)

    # 2. 从存量字典补全完整信息（附检索得分，供测试输出明细）
    std_ids = [r["standard_id"] for r in search_results]
    dict_records = get_standards_by_ids(std_ids)
    score_map = {r["standard_id"]: r for r in search_results}

    candidates = []
    for r in dict_records:
        score = score_map.get(r["std_id"], {})
        candidates.append(CandidateStandard(
            std_id=r["std_id"],
            std_name=r["std_name"],
            std_type=r["std_type"],
            business_definition=r["business_definition"],
            domain_id=r["domain_id"],
            domain_name=r["domain_name"],
            domain_type=r["domain_type"],
            data_example=r["data_example"],
            dense_score=score.get("dense_score", 0.0),
            sparse_score=score.get("sparse_score", 0.0),
            source=score.get("source", ""),
        ))
    return _ensure_exact_name_match(candidates, field_name, field_type)


def _ensure_exact_name_match(candidates, field_name, field_type) -> list[CandidateStandard]:
    """精确同名保底：同类型字典中存在与字段名完全一致的标准时并入候选。

    仅当精确同名标准未出现在检索候选里时生效，避免与检索结果重复。
    """
    name = field_name.strip()
    if any(c["std_name"].strip() == name for c in candidates):
        return candidates

    exact = get_standards_by_name(name, field_type)
    if not exact:
        return candidates

    return [CandidateStandard(
        std_id=r["std_id"],
        std_name=r["std_name"],
        std_type=r["std_type"],
        business_definition=r["business_definition"],
        domain_id=r["domain_id"],
        domain_name=r["domain_name"],
        domain_type=r["domain_type"],
        data_example=r["data_example"],
        dense_score=0.0,
        sparse_score=0.0,
        source="exact",
    ) for r in exact] + candidates


# ============================================================
# 域类型冲突检测（正则规则）
# ============================================================

def _detect_domain_conflict(domain_type: str, data_example: str) -> bool:
    """检测域类型与数据示例是否冲突（委托 common.domain_rules 统一校验）。

    Args:
        domain_type: 域类型格式（如 n..(10), i(15,2), DATE 等）
        data_example: 数据示例

    Returns:
        True 表示冲突，False 表示无冲突
    """
    if not data_example or not domain_type:
        return False
    ok, _ = check_data_example(domain_type, data_example)
    return not ok


# 节点 1: 加载 Excel + 获取备选标准
# ============================================================

def load_and_fetch_node(state: MappingGraphState) -> dict:
    """读取输入 Excel，筛选非代码枚举类字段，向量检索 + 字典回填获取备选标准。"""
    print("\n=== 步骤 1/4: 加载 Excel 并获取备选标准 ===")
    all_rows = read_excel(state["input_file"])

    # 筛选非代码枚举类字段
    rows = [r for r in all_rows if r["field_type"] in NON_ENUM_TYPES]
    enum_count = len(all_rows) - len(rows)
    if enum_count > 0:
        print(f"  筛选: 排除 {enum_count} 行代码枚举类字段，保留 {len(rows)} 行非枚举类字段")

    # 向量检索 + 字典回填获取备选标准
    for row in rows:
        try:
            row["candidates"] = fetch_candidates(
                row["field_name"], row["business_meaning"], row["field_type"]
            )
            row["candidate_fetch_error"] = ""
        except Exception as e:
            row["candidates"] = []
            row["candidate_fetch_error"] = f"候选检索失败: {e}"
            print(f"  行 {row['index']} 候选检索失败: {e}")

    print(f"  备选标准获取完成: {len(rows)} 行")
    return {"rows": rows, "domain_results": [], "selection_results": [], "include_candidates": state.get("include_candidates", True)}


# ============================================================
# 节点 2: 域类型精筛
# ============================================================

def check_domain_node(state: MappingGraphState) -> dict:
    """域类型冲突检测，冲突的备选标准直接淘汰。

    - 标志类: 所有备选标准恒定通过，无需域检查
    - 非标志类: 用正则规则检测冲突，冲突则淘汰该备选标准
    """
    print("\n=== 步骤 2/4: 域类型精筛 ===")
    rows = state["rows"]

    domain_results = []
    for row in rows:
        idx = row["index"]
        field_type = row["field_type"]
        data_example = row["data_example"]
        candidates = row["candidates"]

        if field_type == "标志类":
            row["domain_check_details"] = "标志类字段，域类型恒定通过"
            continue

        if not data_example:
            row["domain_check_details"] = "无数据示例，跳过域类型冲突检测"
            continue

        # 非标志类，有数据示例：逐个检测冲突，冲突则淘汰
        new_candidates = []
        eliminated = []
        details = []

        for cand in candidates:
            conflict = _detect_domain_conflict(cand["domain_type"], data_example)
            if not conflict:
                new_candidates.append(cand)
                details.append(f"备选标准{cand['std_id']}域类型{cand['domain_type']}无冲突")
            else:
                eliminated.append(cand["std_id"])
                details.append(f"备选标准{cand['std_id']}域类型{cand['domain_type']}与数据示例'{data_example}'冲突，已淘汰")

        row["candidates"] = new_candidates
        row["domain_check_details"] = "; ".join(details)

        if eliminated:
            domain_results.append({
                "row_index": idx,
                "eliminated": eliminated,
            })

    print(f"  域类型筛选完成")
    return {"rows": rows, "domain_results": domain_results}


# ============================================================
# 节点 3: LLM 标准选择
# ============================================================

def select_standard_node(state: MappingGraphState) -> dict:
    """调用 LLM 从备选标准中选择最合适的标准。

    无备选标准的行直接标记为"新增标准"。
    """
    print("\n=== 步骤 3/4: LLM 标准选择 ===")
    rows = state["rows"]

    # 筛选有备选标准的行
    rows_to_select = []
    direct_new_count = 0

    for row in rows:
        if row.get("candidate_fetch_error"):
            # 候选检索失败，标记需人工复核
            row["mapping_result"] = "候选检索失败，需人工复核"
            row["selected_std_id"] = ""
            row["selected_std_name"] = ""
            row["llm_reason"] = row["candidate_fetch_error"]
            direct_new_count += 1
        elif not row["candidates"]:
            # 无备选标准，直接新增
            row["mapping_result"] = "新增标准"
            row["selected_std_id"] = ""
            row["selected_std_name"] = ""
            row["llm_reason"] = "无备选标准或备选标准经域类型筛选后全部淘汰，直接新增标准"
            direct_new_count += 1
        else:
            rows_to_select.append({
                "row_index": row["index"],
                "field_name": row["field_name"],
                "business_meaning": row["business_meaning"],
                "data_example": row["data_example"],
                "candidates": [
                    {
                        "std_id": c["std_id"],
                        "std_name": c["std_name"],
                        "business_definition": c["business_definition"],
                    }
                    for c in row["candidates"]
                ],
            })

    if direct_new_count:
        print(f"  {direct_new_count} 行无备选标准，直接标记为新增标准")

    if not rows_to_select:
        print(f"  没有需要 LLM 选择的行")
        return {"rows": rows, "selection_results": []}

    print(f"  共 {len(rows_to_select)} 行需要 LLM 选择标准")
    llm = get_llm()
    results = select_standard(llm, rows_to_select)

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
        row["llm_reason"] = r["reason"]
        if r["extension_suggestion"]:
            row["llm_reason"] += f" 扩展建议: {r['extension_suggestion']}"
        selection_results.append(r)

    if missing_count:
        print(f"  [WARNING] LLM 返回结果缺少 {missing_count} 行，已标记需人工复核")
    print(f"  标准选择完成，共 {len(selection_results)} 条结果")
    return {"rows": rows, "selection_results": selection_results}


# ============================================================
# 节点 4: 写入结果 Excel
# ============================================================

def write_result_node(state: MappingGraphState) -> dict:
    """将落标结果写入输出 Excel。"""
    print("\n=== 步骤 4/4: 写入结果 Excel ===")
    write_excel(
        state["output_file"],
        state["rows"],
        state["input_file"],
        include_candidates=state.get("include_candidates", True),
    )
    return {}
