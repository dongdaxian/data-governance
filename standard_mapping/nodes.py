"""落标处理 LangGraph 节点定义。

图结构：
  START
    ↓
  load_and_fetch   -- 读取 Excel，筛选非枚举类字段，调用接口获取备选标准
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
from standard_mapping.constants import (
    NON_ENUM_TYPES,
    RE_N_VAR, RE_N_FIX,
    RE_A_VAR, RE_A_FIX,
    RE_AN_VAR, RE_AN_FIX,
    RE_ANC_VAR, RE_ANC_FIX,
    RE_I_INT, RE_I_DEC,
    RE_DATE, RE_TIME, RE_DATETIME, RE_TIMESTAMP,
    RE_CHINESE, RE_DIGIT,
)


# ============================================================
# 备选标准接口（TODO: 替换为实际接口调用）
# ============================================================

def fetch_candidates(field_name: str, business_meaning: str, field_type: str) -> list[CandidateStandard]:
    """调用外部接口获取备选标准列表。

    Args:
        field_name: 字段中文名
        business_meaning: 业务含义
        field_type: 字段所属类型

    Returns:
        备选标准列表，每项包含 std_id/std_name/std_type/business_definition/
        domain_id/domain_name/domain_type/data_example
    """
    # TODO: 替换为实际接口调用
    raise NotImplementedError("备选标准接口尚未对接，请实现 fetch_candidates()")


# ============================================================
# 域类型冲突检测（正则规则）
# ============================================================

def _detect_domain_conflict(domain_type: str, data_example: str) -> bool:
    """使用正则规则检测域类型与数据示例是否冲突。

    Args:
        domain_type: 域类型格式（如 n..(10), i(15,2), DATE 等）
        data_example: 数据示例

    Returns:
        True 表示冲突，False 表示无冲突
    """
    if not data_example or not domain_type:
        return False

    dt = domain_type.strip()
    example = str(data_example).strip()

    # 无效数据示例
    if not example or example in ("无", "暂无", "无示例"):
        return False

    # 多个示例取第一个
    for sep in [";", "；", ",", "，", "、"]:
        if sep in example:
            example = example.split(sep)[0].strip()
            break

    if not example:
        return False

    # n..(x) / n!(x): 只允许数字字符
    m_fix = RE_N_FIX.match(dt)
    m_var = RE_N_VAR.match(dt)
    if m_fix or m_var:
        if not example.isdigit():
            return True
        if m_fix and len(example) != int(m_fix.group(1)):
            return True
        if m_var and len(example) > int(m_var.group(1)):
            return True
        return False

    # a..(x) / a!(x): 只允许字母+特殊符号（不允许数字和汉字）
    if RE_A_FIX.match(dt) or RE_A_VAR.match(dt):
        if RE_DIGIT.search(example) or RE_CHINESE.search(example):
            return True
        return False

    # an..(x) / an!(x): 数字+字母+特殊符号（不允许汉字）
    if RE_AN_FIX.match(dt) or RE_AN_VAR.match(dt):
        if RE_CHINESE.search(example):
            return True
        return False

    # anc..(x) / anc!(x): 汉字+数字+字母+特殊符号（基本不冲突）
    if RE_ANC_FIX.match(dt) or RE_ANC_VAR.match(dt):
        return False

    # i(x): x位整数
    m = RE_I_INT.match(dt)
    if m:
        if not example.isdigit():
            return True
        if len(example) != int(m.group(1)):
            return True
        return False

    # i(x, y): x位整数y位小数
    m = RE_I_DEC.match(dt)
    if m:
        int_len = int(m.group(1))
        dec_len = int(m.group(2))
        if "." in example:
            parts = example.split(".", 1)
            int_part, dec_part = parts[0], parts[1]
            if not int_part.isdigit() or not dec_part.isdigit():
                return True
            if len(int_part) != int_len or len(dec_part) != dec_len:
                return True
        else:
            if not example.isdigit():
                return True
            if len(example) != int_len:
                return True
        return False

    # DATE: 年月日，8位数字
    if RE_DATE.match(dt):
        if not (example.isdigit() and len(example) == 8):
            return True
        return False

    # TIME: 时分秒，6位数字
    if RE_TIME.match(dt):
        if not (example.isdigit() and len(example) == 6):
            return True
        return False

    # DATETIME / TIMESTAMP: 年月日时分秒，14位数字
    if RE_DATETIME.match(dt) or RE_TIMESTAMP.match(dt):
        if not (example.isdigit() and len(example) == 14):
            return True
        return False

    # 未知域类型，记录警告
    import logging
    logging.warning(f"未知域类型: {dt}，数据示例: {example}，跳过冲突检测")
    return False


# ============================================================
# 节点 1: 加载 Excel + 获取备选标准
# ============================================================

def load_and_fetch_node(state: MappingGraphState) -> dict:
    """读取输入 Excel，筛选非代码枚举类字段，调用接口获取备选标准。"""
    print("\n=== 步骤 1/4: 加载 Excel 并获取备选标准 ===")
    all_rows = read_excel(state["input_file"])

    # 筛选非代码枚举类字段
    rows = [r for r in all_rows if r["field_type"] in NON_ENUM_TYPES]
    enum_count = len(all_rows) - len(rows)
    if enum_count > 0:
        print(f"  筛选: 排除 {enum_count} 行代码枚举类字段，保留 {len(rows)} 行非枚举类字段")

    # 调用接口获取备选标准
    for row in rows:
        row["candidates"] = fetch_candidates(row["field_name"], row["business_meaning"], row["field_type"])

    print(f"  备选标准获取完成: {len(rows)} 行")
    return {"rows": rows, "domain_results": [], "selection_results": []}


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
        if not row["candidates"]:
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
    for row in rows:
        idx = row["index"]
        if idx not in result_map:
            continue

        r = result_map[idx]
        row["mapping_result"] = r["selection"]
        row["selected_std_id"] = r["selected_std_id"]
        row["selected_std_name"] = r["selected_std_name"]
        row["llm_reason"] = r["reason"]
        if r["extension_suggestion"]:
            row["llm_reason"] += f" 扩展建议: {r['extension_suggestion']}"
        selection_results.append(r)

    print(f"  标准选择完成，共 {len(selection_results)} 条结果")
    return {"rows": rows, "selection_results": selection_results}


# ============================================================
# 节点 4: 写入结果 Excel
# ============================================================

def write_result_node(state: MappingGraphState) -> dict:
    """将落标结果写入输出 Excel。"""
    print("\n=== 步骤 4/4: 写入结果 Excel ===")
    write_excel(state["output_file"], state["rows"], state["input_file"])
    return {}
