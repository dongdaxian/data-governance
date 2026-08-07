# -*- coding: utf-8 -*-
"""LangGraph 节点定义。

图结构：
  START
    |
  load_excel    -- 读取 Excel，初始化 RowData
    |
  check_rules   -- 规则检查：非空(5) + 类型合法(1) + 枚举一致(2) + 域类型匹配(3) + 数据示例(4) + 重复(0)
    |
  +-------------------+
  | check_semantic    |  (并行) LLM 检查业务含义
  | normalize_enum    |  (并行) LLM 规范化枚举值
  +-------------------+
          |
  combine_results -- 汇总所有检查结果，判定通过/不通过
          |
  write_excel     -- 输出结果 Excel
          |
  END
"""

from quality_check.state import GraphState, RowData
from quality_check.excel_utils import read_excel, write_excel
from quality_check.llm import get_llm, check_business_meaning, normalize_enum_values
from quality_check.constants import (
    VALID_FIELD_TYPES,
    DOMAIN_PATTERNS,
    DOMAIN_CHAR_CLASS,
    DOMAIN_WHITELIST,
    INVALID_EXAMPLE_PLACEHOLDERS,
)


# ============================================================
# 域类型解析
# ============================================================

def _parse_domain_type(dt_str):
    """解析域类型字符串，返回 (pattern_key, match_obj) 或 (None, None)。"""
    dt = dt_str.strip()
    for key, regex in DOMAIN_PATTERNS:
        m = regex.match(dt)
        if m:
            return key, m
    return None, None


# ============================================================
# 字符类别判断
# ============================================================

def _is_chinese_char(ch):
    return "\u4e00" <= ch <= "\u9fff"


def _is_digit_char(ch):
    return ch in "0123456789"


def _is_letter_char(ch):
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def _check_char_class(example, char_class):
    """检查数据示例的每个字符是否符合域类型的字符类别限制。

    Args:
        example: 数据示例字符串
        char_class: n/a/an/anc/c/nc/ac/i/date/time/datetime/timestamp

    Returns:
        (is_valid: bool, reason: str)
    """
    for ch in example:
        if char_class == "n":
            if not (_is_digit_char(ch) or ch in "-:/T "):
                return False, f"包含非法字符'{ch}'（数字字符类仅允许数字）"
        elif char_class == "a":
            if _is_digit_char(ch) or _is_chinese_char(ch):
                return False, f"包含不允许的字符'{ch}'（字母+特殊符号类不允许数字和汉字）"
        elif char_class == "an":
            if _is_chinese_char(ch):
                return False, f"包含汉字字符'{ch}'（数字+字母+特殊符号类不允许汉字）"
        elif char_class == "anc":
            pass  # 允许所有字符
        elif char_class == "c":
            if not _is_chinese_char(ch):
                return False, f"包含非汉字字符'{ch}'（纯汉字类仅允许汉字）"
        elif char_class == "nc":
            if not (_is_digit_char(ch) or _is_chinese_char(ch)):
                return False, f"包含不允许的字符'{ch}'（数字+汉字类仅允许数字和汉字）"
        elif char_class == "ac":
            if _is_digit_char(ch):
                return False, f"包含数字字符'{ch}'（字母+汉字类不允许数字）"
        elif char_class == "i":
            if not (_is_digit_char(ch) or ch == "."):
                return False, f"包含非数字字符'{ch}'（数值类仅允许数字和小数点）"
        elif char_class in ("date", "time", "datetime", "timestamp"):
            if not (_is_digit_char(ch) or ch in "-:/T "):
                return False, f"包含非法字符'{ch}'（日期时间类仅允许数字和分隔符-:/空格/T）"
    return True, ""


def _check_length(example, domain_key, match):
    """检查数据示例的长度/精度是否符合域类型的限制。

    Returns:
        (is_valid: bool, reason: str)
    """
    is_nolimit = "_nolimit" in domain_key
    if is_nolimit:
        return True, ""

    is_fixed = "_fix" in domain_key

    # n/a/an/anc/c/nc/ac 变长或定长
    if domain_key in (
        "n_var", "n_fix", "a_var", "a_fix",
        "an_var", "an_fix", "anc_var", "anc_fix",
        "c_var", "c_fix", "nc_var", "nc_fix",
        "ac_var", "ac_fix",
    ):
        limit = int(match.group(1))
        if is_fixed:
            if len(example) != limit:
                return False, f"长度应为{limit}位，实际{len(example)}位"
        else:
            if len(example) > limit:
                return False, f"长度超过最大限制{limit}位，实际{len(example)}位"

    # i(x): 最多 x 位整数
    elif domain_key == "i_int":
        x = int(match.group(1))
        if "." in example:
            return False, f"i({x})为整数类型，数据示例不应包含小数点"
        if len(example) > x:
            return False, f"整数部分不得超过{x}位，实际{len(example)}位"

    # i(x, y): 最多 x 位整数 + 最多 y 位小数
    elif domain_key == "i_dec":
        x = int(match.group(1))
        y = int(match.group(2))
        if "." in example:
            parts = example.split(".", 1)
            int_part, dec_part = parts[0], parts[1]
            if len(int_part) > x:
                return False, f"整数部分不得超过{x}位，实际{len(int_part)}位"
            if len(dec_part) > y:
                return False, f"小数部分不得超过{y}位，实际{len(dec_part)}位"
        else:
            if len(example) > x:
                return False, f"整数部分不得超过{x}位，实际{len(example)}位"

    # 日期时间类：先去除分隔符，再校验数字位数
    elif domain_key in ("date", "time", "datetime", "timestamp",
                        "time_p", "datetime_p", "timestamp_p"):
        digits = example.replace("-", "").replace(":", "").replace(" ", "").replace("T", "")
        if domain_key == "date":
            if len(digits) != 8:
                return False, f"DATE应为8位日期数字（YYYYMMDD），实际{len(digits)}位"
        elif domain_key == "time":
            if len(digits) != 6:
                return False, f"TIME应为6位时间数字（HHMMSS），实际{len(digits)}位"
        elif domain_key in ("datetime", "timestamp"):
            if len(digits) == 8:
                return False, f"{domain_key.upper()}应为日期时间格式（YYYYMMDDHHmmss，14位），数据示例仅包含日期部分"
            if len(digits) != 14:
                return False, f"{domain_key.upper()}应为14位日期时间数字（YYYYMMDDHHmmss），实际{len(digits)}位"
        # time_p / datetime_p / timestamp_p: 带精度参数，仅校验字符类型，不强制位数

    return True, ""


def _check_data_example(domain_key, match, data_example):
    """检查数据示例是否符合域类型的字符类别和长度精度限制。

    Args:
        domain_key: 域类型 pattern key
        match: 正则匹配对象
        data_example: 数据示例字符串

    Returns:
        (is_valid: bool, reason: str)
    """
    # 预处理：多个示例取第一个
    example = str(data_example).strip()
    for sep in [";", "；", ",", "，", "/", "、"]:
        if sep in example:
            example = example.split(sep)[0].strip()
            break

    if not example or example in INVALID_EXAMPLE_PLACEHOLDERS:
        return True, ""

    # 字符类别检查
    char_class = DOMAIN_CHAR_CLASS.get(domain_key)
    if char_class:
        ok, reason = _check_char_class(example, char_class)
        if not ok:
            return False, reason

    # 长度/精度检查
    ok, reason = _check_length(example, domain_key, match)
    if not ok:
        return False, reason

    return True, ""


# ============================================================
# 节点 1: 加载 Excel
# ============================================================

def load_excel_node(state: GraphState) -> dict:
    """读取输入 Excel，初始化 RowData 列表。"""
    print("\n=== 步骤 1/5: 加载 Excel ===")
    rows = read_excel(state["input_file"])
    return {"rows": rows, "semantic_results": [], "enum_results": []}


# ============================================================
# 节点 2: 规则检查（检查 0-5）
# ============================================================

def check_rules_node(state: GraphState) -> dict:
    """规则检查：非空(5) + 类型合法(1) + 枚举一致(2) + 域类型匹配(3) + 数据示例(4) + 重复(0)。

    检查间逻辑依赖：
      5(非空) -> 1(类型合法) -> 2(枚举一致) / 3(域类型匹配) -> 4(数据示例)
      0(重复) 在所有行检查完后批量执行
    """
    print("\n=== 步骤 2/5: 规则检查（非空+类型+枚举+域类型+数据示例+重复）===")
    rows = state["rows"]

    # --- 第一阶段：逐行规则检查 ---

    for row in rows:
        issues = []

        # 检查 5: 必填字段非空
        required = {
            "中文表名": row["table_name"],
            "中文字段名": row["field_name"],
            "域类型": row["domain_type"],
            "数据示例": row["data_example"],
            "字段所属类型": row["field_type"],
            "是否枚举": row["is_enum"],
            "业务定义": row["business_meaning"],
        }
        empty_fields = [name for name, val in required.items() if not val or not str(val).strip()]
        if empty_fields:
            issues.append(f"必填字段为空: {', '.join(empty_fields)}")

        # 检查 1: 字段所属类型合法性（类型为空时跳过）
        type_valid = False
        if row["field_type"] and row["field_type"].strip():
            if row["field_type"] not in VALID_FIELD_TYPES:
                issues.append(
                    f"字段所属类型'{row['field_type']}'不合法，"
                    f"必须是{VALID_FIELD_TYPES}中的一种"
                )
            else:
                type_valid = True

        # 检查 2: 是否枚举一致性 + 枚举值联动（依赖类型合法）
        if type_valid and row["is_enum"] and row["is_enum"].strip():
            is_code_enum = row["field_type"] == "代码枚举类"
            is_enum_val = row["is_enum"].strip()

            if is_enum_val not in ("是", "否"):
                issues.append(f"'是否枚举'填写为'{is_enum_val}'，必须为'是'或'否'")
            else:
                if is_code_enum and is_enum_val != "是":
                    issues.append(f"代码枚举类字段的'是否枚举'必须为'是'，实际为'{is_enum_val}'")
                elif not is_code_enum and is_enum_val != "否":
                    issues.append(f"非代码枚举类字段的'是否枚举'必须为'否'，实际为'{is_enum_val}'")

            # 枚举值联动
            has_enum_values = bool(row["enum_values"] and row["enum_values"].strip())
            if is_enum_val == "是" and not has_enum_values:
                issues.append("'是否枚举'为'是'但枚举值为空")
            elif is_enum_val == "否" and has_enum_values:
                issues.append("'是否枚举'为'否'但枚举值不为空")

        # 检查 3: 域类型与字段所属类型匹配
        domain_key = None
        domain_match = None
        if row["domain_type"] and row["domain_type"].strip():
            domain_key, domain_match = _parse_domain_type(row["domain_type"])
            if domain_key is None:
                issues.append(f"域类型'{row['domain_type']}'格式不合法")
            elif type_valid:
                whitelist = DOMAIN_WHITELIST.get(row["field_type"], set())
                if domain_key not in whitelist:
                    issues.append(
                        f"域类型'{row['domain_type']}'不允许用于字段所属类型'{row['field_type']}'"
                    )
                elif row["field_type"] == "标志类":
                    # 标志类特殊校验：仅允许 n!(1)
                    if domain_match.group(1) != "1":
                        issues.append(
                            f"标志类字段的域类型必须为n!(1)，实际为'{row['domain_type']}'"
                        )

        # 检查 4: 域类型与数据示例相符（依赖域类型格式可解析）
        if domain_key is not None and row["data_example"] and row["data_example"].strip():
            ok, reason = _check_data_example(
                domain_key, domain_match, row["data_example"]
            )
            if not ok:
                issues.append(
                    f"数据示例'{row['data_example']}'不符合域类型"
                    f"'{row['domain_type']}'的限制: {reason}"
                )

        row["rule_issues"] = issues
        row["rule_passed"] = len(issues) == 0

    # --- 第二阶段：批量检查 0: 重复字段名 ---
    seen = {}  # (table_name, field_name) -> list index in rows
    for list_idx, row in enumerate(rows):
        if not row["table_name"] or not row["field_name"]:
            continue
        key = (row["table_name"].strip(), row["field_name"].strip())
        if key in seen:
            dup_msg = f"字段中文名'{row['field_name']}'在表'{row['table_name']}'中重复"
            row["rule_issues"].append(dup_msg)
            row["rule_passed"] = False
            # 同时标记首次出现的行
            first_idx = seen[key]
            first_row = rows[first_idx]
            if dup_msg not in first_row["rule_issues"]:
                first_row["rule_issues"].append(dup_msg)
                first_row["rule_passed"] = False
        else:
            seen[key] = list_idx

    # 统计
    passed = sum(1 for r in rows if r["rule_passed"])
    print(f"  规则检查完成: {passed} 行通过，{len(rows) - passed} 行有问题")
    return {"rows": rows}


# ============================================================
# 节点 3a: LLM 业务含义检查（与节点3b并行执行）
# ============================================================

def check_semantic_node(state: GraphState) -> dict:
    """调用 LLM 批量检查业务含义是否有效。

    仅跳过业务定义为空的行，与规则检查结果互不影响。
    """
    print("\n=== 步骤 3a/5: LLM 业务含义检查 ===")
    rows = state["rows"]

    rows_to_check = [
        {
            "row_index": r["index"],
            "字段中文名": r["field_name"],
            "业务含义": r["business_meaning"],
        }
        for r in rows
        if r["business_meaning"]
    ]

    if not rows_to_check:
        print("  没有需要检查的行（业务定义为空）")
        return {"semantic_results": []}

    print(f"  共 {len(rows_to_check)} 行需要检查业务含义")
    try:
        llm = get_llm()
        results = check_business_meaning(llm, rows_to_check)
        print(f"  业务含义检查完成，共 {len(results)} 条结果")
        return {"semantic_results": results}
    except Exception as e:
        print(f"  [WARNING] LLM 业务含义检查失败: {e}")
        print(f"  跳过语义检查，仅输出规则检查结果")
        return {"semantic_results": []}


# ============================================================
# 节点 3b: LLM 枚举值规范化（与节点3a并行执行）
# ============================================================

def normalize_enum_node(state: GraphState) -> dict:
    """调用 LLM 批量规范化枚举值。

    仅跳过枚举值为空的行，与规则检查结果互不影响。
    """
    print("\n=== 步骤 3b/5: LLM 枚举值规范化 ===")
    rows = state["rows"]

    rows_with_enum = [
        {
            "row_index": r["index"],
            "枚举值": r["enum_values"],
        }
        for r in rows
        if r["enum_values"]
    ]

    if not rows_with_enum:
        print("  没有需要规范化的枚举值")
        return {"enum_results": []}

    print(f"  共 {len(rows_with_enum)} 行有枚举值需要处理")
    try:
        llm = get_llm()
        results = normalize_enum_values(llm, rows_with_enum)
        print(f"  枚举值规范化完成，共 {len(results)} 条结果")
        return {"enum_results": results}
    except Exception as e:
        print(f"  [WARNING] LLM 枚举值规范化失败: {e}")
        print(f"  跳过枚举值规范化，仅输出规则检查结果")
        return {"enum_results": []}


# ============================================================
# 节点 4: 汇总检查结果
# ============================================================

def combine_results_node(state: GraphState) -> dict:
    """汇总规则检查、业务含义检查、枚举规范化的结果，判定通过/不通过。"""
    print("\n=== 步骤 4/5: 汇总检查结果 ===")
    rows = state["rows"]

    semantic_map = {r["row_index"]: r for r in state.get("semantic_results", [])}
    enum_map = {r["row_index"]: r for r in state.get("enum_results", [])}

    for row in rows:
        idx = row["index"]
        reasons = []

        # 规则检查问题
        if row["rule_issues"]:
            reasons.extend(row["rule_issues"])

        # 业务含义检查结果
        if idx in semantic_map:
            sr = semantic_map[idx]
            row["is_meaningful"] = sr["is_meaningful"]
            row["meaning_reason"] = sr["reason"]
            if not sr["is_meaningful"]:
                reasons.append(row["meaning_reason"])
        else:
            # 未被 LLM 检查的行
            if not row["business_meaning"]:
                # 业务定义为空，规则检查5已处理，此处跳过
                row["is_meaningful"] = True
                row["meaning_reason"] = ""
            else:
                # 业务定义非空但 LLM 语义检查未执行（调用异常）
                row["is_meaningful"] = True
                row["meaning_reason"] = "语义检查未执行"
                reasons.append("语义检查未执行")

        # 枚举值规范化结果
        if idx in enum_map:
            er = enum_map[idx]
            row["normalized_enum"] = er["normalized"]
            row["enum_needs_normalization"] = er["needs_normalization"]

        # 判定最终结果
        if reasons:
            row["check_result"] = "不通过"
            row["fail_reason"] = "; ".join(reasons)
        else:
            row["check_result"] = "通过"
            row["fail_reason"] = ""

    passed = sum(1 for r in rows if r["check_result"] == "通过")
    print(f"  检查结果: 通过 {passed} 行，不通过 {len(rows) - passed} 行")
    return {"rows": rows}


# ============================================================
# 节点 5: 写入 Excel
# ============================================================

def write_excel_node(state: GraphState) -> dict:
    """将检查结果写入输出 Excel。"""
    print("\n=== 步骤 5/5: 写入结果 Excel ===")
    write_excel(state["output_file"], state["rows"], state["input_file"])
    return {}
