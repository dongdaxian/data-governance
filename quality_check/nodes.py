# -*- coding: utf-8 -*-
"""LangGraph 节点定义。

图结构：
  START
    |
  load_excel    -- 读取 Excel，初始化 RowData
    |
  check_rules   -- 规则检查：非空 + 类型合法 + 枚举一致 + 域类型匹配 + 数据示例 + 重复
    |
  normalize_enum    -- LLM 规范化枚举值
    |
  check_semantic    -- LLM 检查业务含义
    |
  check_flag     -- 标志类误用检查：仅此前检查无问题的代码枚举类记录，
                    规范化后码值有且仅有"是"和"否"判为应申报标志类
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
    DOMAIN_WHITELIST,
)
from common.domain_rules import parse_domain_type, check_data_example


# ============================================================
# 节点 1: 加载 Excel
# ============================================================

def load_excel_node(state: GraphState) -> dict:
    """读取输入 Excel，初始化 RowData 列表。"""
    print("\n=== 步骤 1/6: 加载 Excel ===")
    rows = read_excel(state["input_file"])
    return {"rows": rows, "semantic_results": [], "enum_results": []}


# ============================================================
# 节点 2: 规则检查
# ============================================================

def check_rules_node(state: GraphState) -> dict:
    """规则检查：非空 + 类型合法 + 枚举一致 + 域类型匹配 + 数据示例 + 重复。

    检查间逻辑依赖：
      非空 -> 类型合法 -> 枚举一致 / 域类型匹配 -> 数据示例
      重复 在所有行检查完后批量执行
    """
    print("\n=== 步骤 2/6: 规则检查（非空+类型+枚举+域类型+数据示例+重复）===")
    rows = state["rows"]

    # --- 预处理：内容仅为"无"的字段视为未填写，替换为空（中文表名除外） ---

    data_fields = (
        "field_name", "field_type", "domain_type",
        "data_example", "is_enum", "business_meaning", "enum_values",
    )
    for row in rows:
        for f in data_fields:
            if row[f] == "无":
                row[f] = ""

    # --- 第一阶段：逐行规则检查 ---

    for row in rows:
        issues = []

        # 必填字段非空
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

        # 字段所属类型合法性（类型为空时跳过）
        type_valid = False
        if row["field_type"] and row["field_type"].strip():
            if row["field_type"] not in VALID_FIELD_TYPES:
                issues.append(
                    f"字段所属类型'{row['field_type']}'不合法，"
                    f"必须是{VALID_FIELD_TYPES}中的一种"
                )
            else:
                type_valid = True

        # 是否枚举一致性 + 枚举值联动（依赖类型合法）
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

        # 域类型与字段所属类型匹配（类型不合法或代码枚举类直接跳过）
        domain_key = None
        domain_match = None
        if (
            type_valid
            and row["field_type"] != "代码枚举类"
            and row["domain_type"]
            and row["domain_type"].strip()
        ):
            domain_key, domain_match = parse_domain_type(row["domain_type"])
            if domain_key is None:
                issues.append(f"域类型'{row['domain_type']}'格式不合法")
            else:
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

        # 域类型与数据示例相符（类型不合法或代码枚举类直接跳过）
        if (
            type_valid
            and row["field_type"] != "代码枚举类"
            and domain_key is not None
            and row["data_example"]
            and row["data_example"].strip()
        ):
            ok, reason = check_data_example(
                row["domain_type"], row["data_example"]
            )
            if not ok:
                issues.append(
                    f"数据示例'{row['data_example']}'不符合域类型"
                    f"'{row['domain_type']}'的限制: {reason}"
                )

        row["rule_issues"] = issues
        row["rule_passed"] = len(issues) == 0

    # --- 第二阶段：批量检查重复字段名 ---
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
# 节点 3b: LLM 业务含义检查（枚举值规范化之后执行）
# ============================================================

def check_semantic_node(state: GraphState) -> dict:
    """调用 LLM 批量检查业务含义是否有效。

    仅跳过业务定义为空的行，与规则检查结果互不影响。
    """
    print("\n=== 步骤 3b/6: LLM 业务含义检查 ===")
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
# 节点 3a: LLM 枚举值规范化（check_rules 之后执行）
# ============================================================

def normalize_enum_node(state: GraphState) -> dict:
    """调用 LLM 批量规范化枚举值。

    仅跳过枚举值为空的行，与规则检查结果互不影响。
    """
    print("\n=== 步骤 3a/6: LLM 枚举值规范化 ===")
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
# 节点 4: 标志类误用检查（3a/3b 都完成后执行）
# ============================================================

def check_flag_node(state: GraphState) -> dict:
    """检查代码枚举类字段的枚举值是否实为标志类。

    仅处理此前检查（规则+业务含义）无问题的记录，使用规范化后的枚举值：
    去掉码值前的代码后，若码值有且仅有"是"和"否"两项，
    则该字段应为标志类而非代码枚举类，报错。
    """
    print("\n=== 步骤 4/6: 标志类误用检查 ===")
    rows = state["rows"]
    semantic_map = {r["row_index"]: r for r in state.get("semantic_results", [])}
    enum_map = {r["row_index"]: r for r in state.get("enum_results", [])}

    flagged = 0
    for row in rows:
        row["flag_issues"] = []

        # 仅检查此前无问题的记录
        if not row["rule_passed"]:
            continue
        sr = semantic_map.get(row["index"])
        if sr and not sr["is_meaningful"]:
            continue

        # 仅检查代码枚举类
        if row["field_type"] != "代码枚举类":
            continue

        # 优先使用规范化后的枚举值，规范化结果缺失时回退原始枚举值
        er = enum_map.get(row["index"])
        normalized = er["normalized"] if er else row["enum_values"]
        if not normalized:
            continue

        # 去掉代码，只看码值
        code_values = set()
        for item in normalized.split(";"):
            item = item.strip()
            if not item:
                continue
            if "-" in item:
                code_values.add(item.partition("-")[2].strip())
            else:
                code_values.add(item)

        if code_values == {"是", "否"}:
            row["flag_issues"].append(
                "枚举值有且仅有'是'和'否'两项，该字段应为标志类而非代码枚举类"
            )
            flagged += 1

    print(f"  发现 {flagged} 行代码枚举类字段实为标志类")
    return {"rows": rows}


# ============================================================
# 节点 5: 汇总检查结果
# ============================================================

def combine_results_node(state: GraphState) -> dict:
    """汇总规则检查、业务含义检查、标志类误用检查、枚举规范化的结果，判定通过/不通过。"""
    print("\n=== 步骤 5/6: 汇总检查结果 ===")
    rows = state["rows"]

    semantic_map = {r["row_index"]: r for r in state.get("semantic_results", [])}
    enum_map = {r["row_index"]: r for r in state.get("enum_results", [])}

    for row in rows:
        idx = row["index"]
        reasons = []

        # 规则检查问题
        if row["rule_issues"]:
            reasons.extend(row["rule_issues"])

        # 标志类误用问题
        if row["flag_issues"]:
            reasons.extend(row["flag_issues"])

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
                # 业务定义为空，规则检查的非空项已处理，此处跳过
                row["is_meaningful"] = True
                row["meaning_reason"] = ""
            else:
                # 业务定义非空但 LLM 语义检查未执行（调用异常）
                row["is_meaningful"] = True
                row["meaning_reason"] = "语义检查未执行"
                reasons.append("语义检查未执行")

        # 枚举值规范化结果
        if idx in enum_map:
            row["normalized_enum"] = enum_map[idx]["normalized"]

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
# 节点 6: 写入 Excel
# ============================================================

def write_excel_node(state: GraphState) -> dict:
    """将检查结果写入输出 Excel。"""
    print("\n=== 步骤 6/6: 写入结果 Excel ===")
    write_excel(state["output_file"], state["rows"], state["input_file"])
    return {}
