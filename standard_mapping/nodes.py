"""落标处理 LangGraph 节点定义。

图结构：
  START
    ↓
  load_and_fetch   -- 读取 Excel，筛选非枚举类字段，调用 Mock 接口获取备选标准
    ↓
  check_domain     -- 域类型精筛（标志类恒定通过，非标志类正则检测冲突+LLM换域）
    ↓
  select_standard  -- LLM 标准选择（复用/复用扩展/新增）
    ↓
  write_result     -- 输出结果 Excel
    ↓
  END
"""

from standard_mapping.state import MappingGraphState, FieldToMap, CandidateStandard
from standard_mapping.excel_utils import read_excel, write_excel
from standard_mapping.llm import get_llm, check_domain_conflict, select_standard
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
# Mock 标准字典池（按所属类型分组）
# ============================================================

_MOCK_STANDARDS: dict[str, list[CandidateStandard]] = {
    "数值类": [
        {"std_id": "STD_NUM_001", "std_name": "交易金额", "std_type": "数值类",
         "business_definition": "记录一笔交易的实际发生金额，单位为元",
         "domain_id": "NUM00001", "domain_name": "金额", "domain_type": "i(15,2)",
         "data_example": "12345.67"},
        {"std_id": "STD_NUM_002", "std_name": "账户余额", "std_type": "数值类",
         "business_definition": "账户当前的可用余额",
         "domain_id": "NUM00001", "domain_name": "金额", "domain_type": "i(15,2)",
         "data_example": "50000.00"},
        {"std_id": "STD_NUM_003", "std_name": "利率", "std_type": "数值类",
         "business_definition": "年化利率百分比",
         "domain_id": "NUM00003", "domain_name": "比例", "domain_type": "i(3,4)",
         "data_example": "3.5000"},
        {"std_id": "STD_NUM_004", "std_name": "交易笔数", "std_type": "数值类",
         "business_definition": "统计周期内的交易总笔数",
         "domain_id": "NUM00002", "domain_name": "数量", "domain_type": "i(10)",
         "data_example": "100"},
        {"std_id": "STD_NUM_005", "std_name": "序号", "std_type": "数值类",
         "business_definition": "记录的顺序编号",
         "domain_id": "NUM00004", "domain_name": "序号", "domain_type": "n..(10)",
         "data_example": "1"},
    ],
    "日期时间类": [
        {"std_id": "STD_DTM_001", "std_name": "开户日期", "std_type": "日期时间类",
         "business_definition": "客户开立账户的日期",
         "domain_id": "DTM00001", "domain_name": "日期", "domain_type": "DATE",
         "data_example": "20240101"},
        {"std_id": "STD_DTM_002", "std_name": "到期日期", "std_type": "日期时间类",
         "business_definition": "产品或合约到期的日期",
         "domain_id": "DTM00001", "domain_name": "日期", "domain_type": "DATE",
         "data_example": "20251231"},
        {"std_id": "STD_DTM_003", "std_name": "交易时间", "std_type": "日期时间类",
         "business_definition": "交易发生的时间",
         "domain_id": "DTM00003", "domain_name": "日期时间", "domain_type": "DATETIME",
         "data_example": "20240101120000"},
        {"std_id": "STD_DTM_004", "std_name": "更新时间", "std_type": "日期时间类",
         "business_definition": "记录最后更新的时间",
         "domain_id": "DTM00004", "domain_name": "时间戳", "domain_type": "TIMESTAMP",
         "data_example": "20240101120000"},
    ],
    "标志类": [
        {"std_id": "STD_FLG_001", "std_name": "是否标志", "std_type": "标志类",
         "business_definition": "通用的是否标志，0表示否，1表示是",
         "domain_id": "FLG00001", "domain_name": "标志", "domain_type": "n!(1)",
         "data_example": "1"},
    ],
    "编码类": [
        {"std_id": "STD_ECD_001", "std_name": "客户编号", "std_type": "编码类",
         "business_definition": "系统中客户的唯一标识编号",
         "domain_id": "ECD00001", "domain_name": "通用编号", "domain_type": "an..(20)",
         "data_example": "CUST20240101"},
        {"std_id": "STD_ECD_002", "std_name": "机构编号", "std_type": "编码类",
         "business_definition": "银行机构的唯一标识编号",
         "domain_id": "ECD00002", "domain_name": "机构编号", "domain_type": "an..(10)",
         "data_example": "B001"},
        {"std_id": "STD_ECD_003", "std_name": "证件号码", "std_type": "编码类",
         "business_definition": "客户证件的号码",
         "domain_id": "ECD00003", "domain_name": "证件号码", "domain_type": "an..(20)",
         "data_example": "110101199001011234"},
        {"std_id": "STD_ECD_004", "std_name": "流水编号", "std_type": "编码类",
         "business_definition": "交易的流水编号",
         "domain_id": "ECD00004", "domain_name": "数字编码", "domain_type": "n..(10)",
         "data_example": "20240101001"},
        {"std_id": "STD_ECD_005", "std_name": "产品代码", "std_type": "编码类",
         "business_definition": "金融产品的唯一代码",
         "domain_id": "ECD00001", "domain_name": "通用编号", "domain_type": "an..(20)",
         "data_example": "P001"},
    ],
    "文本类": [
        {"std_id": "STD_TXT_001", "std_name": "客户名称", "std_type": "文本类",
         "business_definition": "客户的姓名或企业名称",
         "domain_id": "TXT00002", "domain_name": "名称", "domain_type": "anc..(100)",
         "data_example": "张三"},
        {"std_id": "STD_TXT_002", "std_name": "产品名称", "std_type": "文本类",
         "business_definition": "金融产品的名称",
         "domain_id": "TXT00002", "domain_name": "名称", "domain_type": "anc..(100)",
         "data_example": "活期存款"},
        {"std_id": "STD_TXT_003", "std_name": "地址描述", "std_type": "文本类",
         "business_definition": "客户的居住地址描述",
         "domain_id": "TXT00003", "domain_name": "描述", "domain_type": "anc..(500)",
         "data_example": "北京市朝阳区"},
        {"std_id": "STD_TXT_004", "std_name": "备注说明", "std_type": "文本类",
         "business_definition": "通用的备注说明文本",
         "domain_id": "TXT00001", "domain_name": "通用文本", "domain_type": "anc..(200)",
         "data_example": "无"},
        {"std_id": "STD_TXT_005", "std_name": "客户简称", "std_type": "文本类",
         "business_definition": "客户的简称或缩写",
         "domain_id": "TXT00004", "domain_name": "短文本", "domain_type": "an..(50)",
         "data_example": "ABC"},
    ],
}

# Mock 域池（按所属类型分组，用于换域建议）
_MOCK_DOMAINS: dict[str, list[dict]] = {
    "数值类": [
        {"domain_id": "NUM00001", "domain_name": "金额", "domain_type": "i(15,2)"},
        {"domain_id": "NUM00002", "domain_name": "数量", "domain_type": "i(10)"},
        {"domain_id": "NUM00003", "domain_name": "比例", "domain_type": "i(3,4)"},
        {"domain_id": "NUM00004", "domain_name": "序号", "domain_type": "n..(10)"},
    ],
    "日期时间类": [
        {"domain_id": "DTM00001", "domain_name": "日期", "domain_type": "DATE"},
        {"domain_id": "DTM00002", "domain_name": "时间", "domain_type": "TIME"},
        {"domain_id": "DTM00003", "domain_name": "日期时间", "domain_type": "DATETIME"},
        {"domain_id": "DTM00004", "domain_name": "时间戳", "domain_type": "TIMESTAMP"},
    ],
    "标志类": [
        {"domain_id": "FLG00001", "domain_name": "标志", "domain_type": "n!(1)"},
    ],
    "编码类": [
        {"domain_id": "ECD00001", "domain_name": "通用编号", "domain_type": "an..(20)"},
        {"domain_id": "ECD00002", "domain_name": "机构编号", "domain_type": "an..(10)"},
        {"domain_id": "ECD00003", "domain_name": "证件号码", "domain_type": "an..(20)"},
        {"domain_id": "ECD00004", "domain_name": "数字编码", "domain_type": "n..(10)"},
        {"domain_id": "ECD00005", "domain_name": "固定编码", "domain_type": "an!(8)"},
    ],
    "文本类": [
        {"domain_id": "TXT00001", "domain_name": "通用文本", "domain_type": "anc..(200)"},
        {"domain_id": "TXT00002", "domain_name": "名称", "domain_type": "anc..(100)"},
        {"domain_id": "TXT00003", "domain_name": "描述", "domain_type": "anc..(500)"},
        {"domain_id": "TXT00004", "domain_name": "短文本", "domain_type": "an..(50)"},
        {"domain_id": "TXT00005", "domain_name": "纯字母代码", "domain_type": "a..(20)"},
    ],
}


# ============================================================
# Mock API: 获取备选标准
# ============================================================

def _has_keyword_overlap(name1: str, name2: str) -> bool:
    """检查两个名称是否共享2字以上的子串。"""
    if not name1 or not name2:
        return False
    # 完全包含
    if name1 in name2 or name2 in name1:
        return True
    # 共享2字子串
    for i in range(len(name1) - 1):
        sub = name1[i : i + 2]
        if sub in name2:
            return True
    return False


def _fetch_candidates(field: FieldToMap) -> list[CandidateStandard]:
    """Mock API: 根据字段名关键词匹配返回备选标准。

    返回 0-3 个备选标准，同所属类型内匹配。
    某些备选标准的域类型可能与数据示例冲突（触发换域流程）。
    """
    field_name = field["field_name"]
    field_type = field["field_type"]

    pool = _MOCK_STANDARDS.get(field_type, [])
    if not pool:
        return []

    # 关键词匹配：字段名与标准名共享2字以上子串
    candidates = []
    for std in pool:
        if _has_keyword_overlap(field_name, std["std_name"]):
            # 返回副本，避免修改原始池
            candidates.append(dict(std))

    return candidates[:3]


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

    # 未知域类型，不判定冲突
    return False


# ============================================================
# 节点 1: 加载 Excel + 获取备选标准
# ============================================================

def load_and_fetch_node(state: MappingGraphState) -> dict:
    """读取输入 Excel，筛选非代码枚举类字段，调用 Mock 接口获取备选标准。"""
    print("\n=== 步骤 1/4: 加载 Excel 并获取备选标准 ===")
    all_rows = read_excel(state["input_file"])

    # 筛选非代码枚举类字段
    rows = [r for r in all_rows if r["field_type"] in NON_ENUM_TYPES]
    enum_count = len(all_rows) - len(rows)
    if enum_count > 0:
        print(f"  筛选: 排除 {enum_count} 行代码枚举类字段，保留 {len(rows)} 行非枚举类字段")

    # 调用 Mock 接口获取备选标准
    with_candidates = 0
    without_candidates = 0
    for row in rows:
        candidates = _fetch_candidates(row)
        row["candidates"] = candidates
        if candidates:
            with_candidates += 1
        else:
            without_candidates += 1

    print(f"  备选标准获取完成: {with_candidates} 行有备选标准，{without_candidates} 行无备选标准")
    return {"rows": rows, "domain_results": [], "selection_results": []}


# ============================================================
# 节点 2: 域类型精筛
# ============================================================

def check_domain_node(state: MappingGraphState) -> dict:
    """域类型冲突检测与换域建议。

    - 标志类: 所有备选标准恒定通过，无需域检查
    - 非标志类: 先用正则规则检测冲突，冲突时调用 LLM 寻找替代域
    """
    print("\n=== 步骤 2/4: 域类型精筛 ===")
    rows = state["rows"]

    # === 第一遍：正则检测冲突，收集需要 LLM 判断的项 ===
    llm_check_items: list[dict] = []
    # 每个候选的检测结果: {row_index: [(candidate_index, "pass"|"conflict"), ...]}
    check_status: dict[int, list[tuple[int, str]]] = {}

    for row in rows:
        idx = row["index"]
        field_type = row["field_type"]
        data_example = row["data_example"]
        candidates = row["candidates"]
        check_status[idx] = []

        if field_type == "标志类":
            # 标志类恒定通过
            for ci in range(len(candidates)):
                check_status[idx].append((ci, "pass"))
            row["domain_check_details"] = "标志类字段，域类型恒定通过"
            row["domain_change_suggestion"] = ""
            continue

        if not candidates:
            row["domain_check_details"] = "无备选标准"
            row["domain_change_suggestion"] = ""
            continue

        if not data_example:
            # 无数据示例，无法检测冲突，全部通过
            for ci in range(len(candidates)):
                check_status[idx].append((ci, "pass"))
            row["domain_check_details"] = "无数据示例，跳过域类型冲突检测"
            row["domain_change_suggestion"] = ""
            continue

        # 非标志类，有数据示例：逐个检测冲突
        available_domains = _MOCK_DOMAINS.get(field_type, [])
        details = []

        for ci, cand in enumerate(candidates):
            conflict = _detect_domain_conflict(cand["domain_type"], data_example)
            if not conflict:
                check_status[idx].append((ci, "pass"))
                details.append(
                    f"备选标准{cand['std_id']}域类型{cand['domain_type']}无冲突"
                )
            else:
                check_status[idx].append((ci, "conflict"))
                details.append(
                    f"备选标准{cand['std_id']}域类型{cand['domain_type']}与数据示例'{data_example}'冲突"
                )
                llm_check_items.append({
                    "row_index": idx,
                    "candidate_index": ci,
                    "field_name": row["field_name"],
                    "field_type": field_type,
                    "data_example": data_example,
                    "current_domain_id": cand["domain_id"],
                    "current_domain_name": cand["domain_name"],
                    "current_domain_type": cand["domain_type"],
                    "available_domains": [
                        d for d in available_domains
                        if d["domain_id"] != cand["domain_id"]
                    ],
                })

        row["domain_check_details"] = "; ".join(details)

    # === 调用 LLM 检测冲突项 ===
    if llm_check_items:
        print(f"  共 {len(llm_check_items)} 条冲突项需要 LLM 判断")
        llm = get_llm()
        llm_results = check_domain_conflict(llm, llm_check_items)
    else:
        print(f"  无冲突项需要 LLM 判断")
        llm_results = []

    # === 第二遍：应用 LLM 结果，过滤候选标准 ===
    llm_map: dict[tuple[int, int], dict] = {}
    for lr in llm_results:
        llm_map[(lr["row_index"], lr["candidate_index"])] = lr

    domain_results = []
    for row in rows:
        idx = row["index"]
        if idx not in check_status:
            continue

        candidates = row["candidates"]
        new_candidates = []
        suggestions = []
        eliminated = []

        for ci, status in check_status[idx]:
            if ci >= len(candidates):
                continue
            cand = candidates[ci]

            if status == "pass":
                new_candidates.append(cand)
            elif status == "conflict":
                lr = llm_map.get((idx, ci))
                if lr and lr["needs_domain_change"]:
                    # 换域成功，更新候选标准的域信息
                    old_domain = f"{cand['domain_name']}({cand['domain_type']})"
                    cand["domain_id"] = lr["new_domain_id"]
                    cand["domain_name"] = lr["new_domain_name"]
                    cand["domain_type"] = lr["new_domain_type"]
                    new_domain = f"{cand['domain_name']}({cand['domain_type']})"
                    new_candidates.append(cand)
                    suggestions.append(
                        f"如使用标准{cand['std_id']}，需将域从 {old_domain} 换为 {new_domain}"
                    )
                    domain_results.append({
                        "row_index": idx,
                        "candidate_index": ci,
                        "result": "换域",
                        "reason": lr["reason"],
                    })
                else:
                    # 无替代域，淘汰该备选标准
                    eliminated.append(cand["std_id"])
                    domain_results.append({
                        "row_index": idx,
                        "candidate_index": ci,
                        "result": "淘汰",
                        "reason": lr["reason"] if lr else "无LLM结果",
                    })

        row["candidates"] = new_candidates
        row["domain_change_suggestion"] = "; ".join(suggestions) if suggestions else ""

        if eliminated:
            row["domain_check_details"] += f"; 已淘汰备选标准: {', '.join(eliminated)}"

    passed = sum(1 for r in rows if r["candidates"])
    print(f"  域类型精筛完成: {passed} 行保留备选标准，{len(rows) - passed} 行无备选标准")
    return {"rows": rows, "domain_results": domain_results}


# ============================================================
# 节点 3: LLM 标准选择
# ============================================================

def select_standard_node(state: MappingGraphState) -> dict:
    """调用 LLM 从精筛后的备选标准中选择最合适的标准。

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
            row["llm_reason"] = "无备选标准或备选标准经域类型精筛后全部淘汰，直接新增标准"
            direct_new_count += 1
        else:
            rows_to_select.append({
                "row_index": row["index"],
                "field_name": row["field_name"],
                "field_type": row["field_type"],
                "business_meaning": row["business_meaning"],
                "data_example": row["data_example"],
                "candidates": [
                    {
                        "std_id": c["std_id"],
                        "std_name": c["std_name"],
                        "business_definition": c["business_definition"],
                        "domain_type": c["domain_type"],
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
