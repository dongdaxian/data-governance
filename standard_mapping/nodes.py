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
from standard_mapping.llm import (
    get_llm,
    select_standard,
    rewrite_field_names,
    rewrite_datetime_field_names,
    classify_numeric_fields,
)
from standard_mapping.constants import NON_ENUM_TYPES
from standard_mapping.preprocess import preprocess_field_name, detect_datetime_domain
from common.domain_rules import check_data_example
from common.vector_store import search as vector_search, translate_milvus_error
from common.exceptions import NonRetryableError
from common.llm_client import build_row_result_map, append_module_log
from config import WRITE_INTERVAL_ROWS
from common.dictionary_store import (
    get_by_ids as get_standards_by_ids,
)


# ============================================================
# 备选标准获取（向量检索 + 字典回填）
# ============================================================

def fetch_candidates(field_name: str, business_meaning: str, field_type: str) -> list[CandidateStandard]:
    """向量检索 + 字典回填，获取备选标准列表。

    流程:
      1. 调用向量检索（稠密 top10 + 稀疏 top10 -> 合并去重）
      2. 根据返回的标准编号，从存量字典补全完整信息

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
        return []

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
            name_sparse_score=score.get("name_sparse_score", 0.0),
            meaning_sparse_score=score.get("meaning_sparse_score", 0.0),
            source=score.get("source", ""),
        ))
    return candidates


def fetch_candidates_preprocessed(
    field_name: str, business_meaning: str, field_type: str, row_index: int
) -> list[CandidateStandard]:
    """预处理（近义词扩展）后用多个查询名分别检索，按标准编号合并去重。

    合并规则：
    - 以 standard_id 为键，首次出现的条目作为基座（保持原查询名结果靠前）。
    - dense_score / name_sparse_score / meaning_sparse_score 逐项取各查询名下的最大值。
    - source 组装为可读文本，记录每条候选被哪些查询名的哪些检索路召回，
      如"客户编号dense召回；客户号dense、name_sparse召回"。
    """
    search_names = preprocess_field_name(field_name)

    # 得分>0 判定候选在某个查询名下命中了哪些检索路
    score_path_fields = (
        ("dense_score", "dense"),
        ("name_sparse_score", "name_sparse"),
        ("meaning_sparse_score", "meaning_sparse"),
    )

    merged: dict[str, CandidateStandard] = {}
    hit_parts: dict[str, list[str]] = {}  # std_id -> ["客户编号dense召回", "客户号name_sparse召回", ...]
    for name in search_names:
        for cand in fetch_candidates(name, business_meaning, field_type):
            sid = cand["std_id"]
            paths = [p for sf, p in score_path_fields if cand.get(sf, 0.0) > 0.0]
            if paths:
                hit_parts.setdefault(sid, []).append(f"{name}{'、'.join(paths)}召回")

            if sid not in merged:
                merged[sid] = cand
                continue
            existing = merged[sid]
            for score_field, _ in score_path_fields:
                if cand.get(score_field, 0.0) > existing.get(score_field, 0.0):
                    existing[score_field] = cand.get(score_field, 0.0)

    for sid, cand in merged.items():
        cand["source"] = "；".join(hit_parts.get(sid, []))
    return list(merged.values())


def _build_retrieval_field_log(row: FieldToMap) -> str:
    """组装检索字段说明：先输出原始字段，再说明预处理（改写/近义词扩展）结果。

    例：
      - 无预处理：  行 24 检索字段: '开户日期'
      - 近义词扩展：行 28 检索字段: '客户编号'，预处理（近义词）扩展为 ['客户编号', '客户号']
      - LLM 改写：  行 63 检索字段: '模板状态'，预处理（改写）将字段名改写为 '模板启用标志'
    """
    idx = row["index"]
    original = row["field_name"]
    used = row["rewritten_field_name"]
    parts = [f"  行 {idx} 检索字段: '{original}'"]
    if used != original:
        parts.append(f"预处理（改写）将字段名改写为 '{used}'")
    search_names = preprocess_field_name(used)
    if len(search_names) > 1:
        parts.append(f"预处理（近义词）扩展为 {search_names}")
    return "，".join(parts)


# ============================================================
# 标志类字段名改写（检索前预处理，LLM 改写）
# ============================================================

def _parse_enum_values(enum_text: str) -> list[tuple[str, str]]:
    """解析"码-值;码-值"为 (码, 值) 列表；无"-"时整段作为值。"""
    pairs = []
    for part in str(enum_text or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            code, value = part.split("-", 1)
            pairs.append((code.strip(), value.strip()))
        else:
            pairs.append(("", part))
    return pairs


def _needs_field_name_rewrite(field_type: str, enum_values: str) -> bool:
    """标志类 + 枚举值非空 + 枚举值不是恰为{是,否}（标准二值标志）才需要改写。"""
    if field_type != "标志类":
        return False
    values = [v for _, v in _parse_enum_values(enum_values)]
    if not values:
        return False
    return set(values) != {"是", "否"}


def rewrite_flag_fields(rows: list[FieldToMap]) -> None:
    """对标志类且枚举值非'是/否'的字段做字段名/业务定义改写（预处理）。

    - 命中行：row["rewritten_field_name"] / row["rewritten_business_meaning"] = 改写结果，
      并日志记录 改写前->后（含枚举值）。
    - 未命中/LLM 缺失行：回退原始名/原始业务定义。
    - LLM 调用整体失败：warning 后全部回退原始值，不中断流程。
    """
    target = [r for r in rows if _needs_field_name_rewrite(r["field_type"], r["enum_values"])]
    if not target:
        return
    llm = get_llm()
    try:
        results = rewrite_field_names(llm, [{
            "row_index": r["index"],
            "field_name": r["field_name"],
            "business_meaning": r["business_meaning"],
            "enum_values": r["enum_values"],
            "data_example": r["data_example"],
        } for r in target])
        result_map, duplicate_indices = build_row_result_map(results)
        for r in target:
            if r["index"] in duplicate_indices or r["index"] not in result_map:
                print(f"  [WARNING] 行 {r['index']} 字段名改写结果缺失/重复，使用原始值")
                continue
            item = result_map[r["index"]]
            rewritten_name = item.get("rewritten_field_name", "").strip()
            rewritten_meaning = item.get("rewritten_business_meaning", "").strip()
            if not rewritten_name and not rewritten_meaning:
                continue
            if rewritten_name:
                r["rewritten_field_name"] = rewritten_name
            if rewritten_meaning:
                r["rewritten_business_meaning"] = rewritten_meaning
            msg = (f"  行 {r['index']} 字段名改写: '{r['field_name']}' -> '{r['rewritten_field_name']}' | "
                   f"业务定义改写: '{r['business_meaning']}' -> '{r['rewritten_business_meaning']}' "
                   f"（枚举值: {r['enum_values']}）")
            print(msg)
            append_module_log("standard_mapping", msg + "\n")
    except Exception as e:
        print(f"  [WARNING] 字段名改写 LLM 调用失败，全部使用原始字段名/业务定义: {e}")


# ============================================================
# 数值类字段指标/字典筛选（检索前预处理，LLM 判断）
# ============================================================

def filter_numeric_indicator_fields(rows: list[FieldToMap]) -> None:
    """对数值类字段做指标/字典筛选（预处理，LLM 判断）。

    - 只处理 field_type == "数值类" 的行，用 字段名+业务口径 送 LLM 判定。
    - 判定为指标的行直接从 rows 剔除（输出结果列留空，与代码枚举类排除一致）。
    - 单行结果缺失/重复：保守保留该行（视为字典），warning 提示。
    - LLM 调用整体失败：warning 后保留全部数值类行，不中断流程。
    """
    target = [r for r in rows if r["field_type"] == "数值类"]
    if not target:
        return
    llm = get_llm()
    try:
        results = classify_numeric_fields(llm, [{
            "row_index": r["index"],
            "field_name": r["field_name"],
            "business_caliber": r.get("business_caliber", ""),
        } for r in target])
        result_map, duplicate_indices = build_row_result_map(results)
        reasoning_map = {item["row_index"]: item.get("reasoning", "") for item in results}
        removed = []
        for r in target:
            if r["index"] in duplicate_indices or r["index"] not in result_map:
                print(f"  [WARNING] 行 {r['index']} 数值类指标筛选结果缺失/重复，保留该行")
                continue
            item = result_map[r["index"]]
            if not item.get("is_indicator"):
                continue
            removed.append(r)
        for r in removed:
            msg = (f"  行 {r['index']} 数值类字段判定为指标，剔除: '{r['field_name']}' | "
                   f"口径: {r.get('business_caliber', '')[:60]} | "
                   f"reasoning: {reasoning_map.get(r['index'], '')}")
            print(msg)
            append_module_log("standard_mapping", msg + "\n")
        if removed:
            rows[:] = [r for r in rows if r not in removed]
            print(f"  数值类指标筛选: 剔除 {len(removed)} 行指标字段，保留 {len(rows)} 行")
    except Exception as e:
        print(f"  [WARNING] 数值类指标筛选 LLM 调用失败，保留全部数值类行: {e}")


# ============================================================
# 日期时间字段名改写（检索前预处理，LLM 改写）
# ============================================================

def rewrite_datetime_fields(rows: list[FieldToMap]) -> None:
    """对日期时间类字段做字段名改写（预处理）。

    - 只处理 field_type == "日期时间类" 的行；用数据示例判定日期/时间/时间戳
      （复用 domain_rules 宽松口径），命中则送 LLM 改写为"××日期/时间/时间戳"。
    - 字段名已以匹配后缀结尾（如"开户日期"）跳过 LLM，保持原名。
    - 命中行：row["rewritten_field_name"] = 改写结果，日志记录 改写前->后。
    - 未命中/LLM 缺失行：回退原始名。
    - LLM 调用整体失败：warning 后全部回退原始值，不中断流程。
    """
    target = []
    for r in rows:
        if r["field_type"] != "日期时间类":
            continue
        suffix = detect_datetime_domain(r["data_example"])
        if not suffix:
            continue
        if r["field_name"].endswith(suffix):
            # 已以匹配后缀结尾（语义已明确），无需改写
            continue
        r["datetime_rewrite_suffix"] = suffix
        target.append(r)
    if not target:
        return
    llm = get_llm()
    try:
        results = rewrite_datetime_field_names(llm, [{
            "row_index": r["index"],
            "field_name": r["field_name"],
            "business_meaning": r["business_meaning"],
            "data_example": r["data_example"],
            "detected_type": r["datetime_rewrite_suffix"],
        } for r in target])
        result_map, duplicate_indices = build_row_result_map(results)
        for r in target:
            if r["index"] in duplicate_indices or r["index"] not in result_map:
                print(f"  [WARNING] 行 {r['index']} 日期时间字段名改写结果缺失/重复，使用原始值")
                continue
            item = result_map[r["index"]]
            rewritten_name = item.get("rewritten_field_name", "").strip()
            if not rewritten_name:
                continue
            r["rewritten_field_name"] = rewritten_name
            msg = (f"  行 {r['index']} 日期时间字段名改写: '{r['field_name']}' -> "
                   f"'{r['rewritten_field_name']}' "
                   f"（检测类型: {r['datetime_rewrite_suffix']}，数据示例: {r['data_example']}）")
            print(msg)
            append_module_log("standard_mapping", msg + "\n")
    except Exception as e:
        print(f"  [WARNING] 日期时间字段名改写 LLM 调用失败，全部使用原始字段名: {e}")


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

    # 字段名/业务定义改写（预处理）：默认原始值，先日期时间类（数据示例判定）后标志类（枚举值判定）经 LLM 改写
    for row in rows:
        row["rewritten_field_name"] = row["field_name"]
        row["rewritten_business_meaning"] = row["business_meaning"]
    # 数值类指标筛选（用原始字段名+业务口径判断，须在字段名改写前执行）
    filter_numeric_indicator_fields(rows)
    rewrite_datetime_fields(rows)
    rewrite_flag_fields(rows)

    # 向量检索 + 字典回填获取备选标准（连续不可重试错误熔断）
    consecutive_config_errors = 0
    for row in rows:
        try:
            row["candidates"] = fetch_candidates_preprocessed(
                row["rewritten_field_name"], row["rewritten_business_meaning"], row["field_type"], row["index"]
            )
            row["candidate_fetch_error"] = ""
            consecutive_config_errors = 0
            # 输出当前检索字段说明（原始字段 + 预处理结果），候选明细之前
            field_log = _build_retrieval_field_log(row)
            print(field_log)
            append_module_log("standard_mapping", field_log + "\n")
            # 打印候选得分明细到运行日志，并写入模块日志文件（排查检索质量用）
            log_lines = []
            for c in row["candidates"]:
                line = (
                    f"  行 {row['index']} 候选 {c['std_id']} {c['std_name']} | "
                    f"dense={c.get('dense_score', 0.0)} "
                    f"name_sparse={c.get('name_sparse_score', 0.0)} "
                    f"meaning_sparse={c.get('meaning_sparse_score', 0.0)}"
                )
                print(line)
                log_lines.append(line)
            if log_lines:
                append_module_log("standard_mapping", "\n".join(log_lines) + "\n")
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
    按 WRITE_INTERVAL_ROWS 行一组处理，每完成一组即增量写盘输出文件，
    避免大输入时等待全部行处理完才看到结果。
    """
    print("\n=== 步骤 3/4: LLM 标准选择 ===")
    rows = state["rows"]
    include_candidates = state.get("include_candidates", True)

    selection_results = []
    llm = get_llm()

    for chunk_start in range(0, len(rows), WRITE_INTERVAL_ROWS):
        chunk = rows[chunk_start:chunk_start + WRITE_INTERVAL_ROWS]
        batch_no = chunk_start // WRITE_INTERVAL_ROWS + 1
        print(f"  --- 批次 {batch_no}（输入第 {chunk_start + 1}-{chunk_start + len(chunk)} 行）---")

        # 筛选有备选标准的行
        rows_to_select = []
        direct_new_count = 0

        for row in chunk:
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
                    "field_name": row["rewritten_field_name"],
                    "field_type": row["field_type"],
                    "business_meaning": row["rewritten_business_meaning"],
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
            print(f"  批次 {batch_no}: {direct_new_count} 行无备选标准，直接标记为新增标准")

        if rows_to_select:
            print(f"  批次 {batch_no}: 共 {len(rows_to_select)} 行需要 LLM 选择标准")
            results = select_standard(llm, rows_to_select)

            # 应用 LLM 结果
            result_map, duplicate_indices = build_row_result_map(results)
            sent_indices = {r["row_index"] for r in rows_to_select}
            missing_count = 0
            for row in chunk:
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
                row["mapping_result"] = r["selection"]
                row["selected_std_id"] = r["selected_std_id"]
                row["selected_std_name"] = r["selected_std_name"]
                row["llm_reason"] = r["reasoning"]
                if r["extension_suggestion"]:
                    row["llm_reason"] += f" 扩展建议: {r['extension_suggestion']}"
                selection_results.append(r)

            if missing_count:
                print(f"  [WARNING] LLM 返回结果缺少 {missing_count} 行，已标记需人工复核")

        # 每完成一组即增量写盘（首组新建文件，后续组追加填充）
        write_excel(
            state["output_file"],
            rows,
            state["input_file"],
            include_candidates=include_candidates,
            append=chunk_start > 0,
        )

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
