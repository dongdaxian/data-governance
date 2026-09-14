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
  check_enum_type_consistency -- 类型与枚举值一致性检查：代码枚举类码值为"是/否"判为应申报标志类；
                                标志类枚举值超过两项判为应申报代码枚举类
          |
  combine_results -- 汇总所有检查结果，判定通过/不通过
          |
  soft_check     -- 软性检查：字段所属类型/枚举值数量与语义提示
                    （依赖字段非空即执行，不影响检查结果列）
          |
  write_excel     -- 输出结果 Excel
          |
  END
"""

from quality_check.state import GraphState, RowData
from quality_check.excel_utils import read_excel, write_excel
from quality_check.llm import (
    get_llm,
    check_business_meaning,
    normalize_enum_values,
    check_field_types,
    check_enum_antonyms,
)
from quality_check.constants import (
    VALID_FIELD_TYPES,
    DOMAIN_WHITELIST,
)
from common.domain_rules import parse_domain_type, check_data_example, RE_CHINESE
from common.llm_client import build_row_result_map


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
    """规则检查：非空 + 中文名含中文字符 + 类型合法 + 枚举一致 + 域类型匹配 + 数据示例 + 重复。

    检查间逻辑依赖：
      非空 -> 类型合法 -> 枚举一致 / 域类型匹配 -> 数据示例
      重复 在所有行检查完后批量执行
    """
    print("\n=== 步骤 2/6: 规则检查（非空+中文名+类型+枚举+域类型+数据示例+重复）===")
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

        # 字段中文名必须包含至少一个中文字符
        if row["field_name"] and not RE_CHINESE.search(str(row["field_name"]).strip()):
            issues.append(f"字段中文名'{row['field_name']}'必须包含至少一个中文字符")

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
            # 代码枚举类、标志类必须填"是"并携带枚举值
            is_enum_required = row["field_type"] in ("代码枚举类", "标志类")
            is_enum_val = row["is_enum"].strip()

            if is_enum_val not in ("是", "否"):
                issues.append(f"'是否枚举'填写为'{is_enum_val}'，必须为'是'或'否'")
            else:
                if is_enum_required and is_enum_val != "是":
                    issues.append(f"{row['field_type']}字段的'是否枚举'必须为'是'，实际为'{is_enum_val}'")
                elif not is_enum_required and is_enum_val != "否":
                    issues.append(f"非代码枚举类/标志类字段的'是否枚举'必须为'否'，实际为'{is_enum_val}'")

            # 枚举值联动
            has_enum_values = bool(row["enum_values"] and row["enum_values"].strip())
            if is_enum_val == "是" and not has_enum_values:
                issues.append("'是否枚举'为'是'但枚举值为空")
            elif is_enum_val == "否" and has_enum_values:
                issues.append("'是否枚举'为'否'但枚举值不为空")

        # 域类型与字段所属类型匹配（类型不合法或枚举类/标志类直接跳过）
        domain_key = None
        if (
            type_valid
            and row["field_type"] not in ("代码枚举类", "标志类")
            and row["domain_type"]
            and row["domain_type"].strip()
        ):
            domain_key, _ = parse_domain_type(row["domain_type"])
            if domain_key is None:
                issues.append(f"域类型'{row['domain_type']}'格式不合法")
            else:
                whitelist = DOMAIN_WHITELIST.get(row["field_type"], set())
                if domain_key not in whitelist:
                    issues.append(
                        f"域类型'{row['domain_type']}'不允许用于字段所属类型'{row['field_type']}'"
                    )

        # 域类型与数据示例相符（类型不合法或枚举类/标志类直接跳过）
        if (
            type_valid
            and row["field_type"] not in ("代码枚举类", "标志类")
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
# 节点 4: 字段类型与枚举值一致性检查（3a/3b 都完成后执行）
# ============================================================

def _enum_item_count(enum_values) -> int:
    """统计枚举值拆分的项数（规范化格式以分号分隔）。"""
    if not enum_values:
        return 0
    return len([p for p in str(enum_values).split(";") if p.strip()])


def check_enum_type_consistency_node(state: GraphState) -> dict:
    """检查字段所属类型与枚举值数量/码值是否一致。

    使用规范化后的枚举值做两类硬性检查：
      - 代码枚举类：码值有且仅有"是"和"否"时，应为标志类；
      - 标志类：枚举值超过两项时，应为代码枚举类。
    """
    print("\n=== 步骤 4/6: 类型与枚举值一致性检查 ===")
    rows = state["rows"]
    semantic_map, duplicate_semantic_indices = build_row_result_map(
        state.get("semantic_results", [])
    )
    enum_map, duplicate_enum_indices = build_row_result_map(
        state.get("enum_results", [])
    )

    flagged = 0
    for row in rows:
        row["flag_issues"] = []

        # LLM 结果重复时不做互斥判断，交由汇总节点统一标记人工复核
        if row["index"] in duplicate_semantic_indices or row["index"] in duplicate_enum_indices:
            continue

        if row["field_type"] not in ("代码枚举类", "标志类") or not row["enum_values"]:
            continue

        er = enum_map.get(row["index"])
        # 枚举值缺代码的行已在汇总阶段判不通过，跳过标志类误用检查
        if er is not None and not er["has_codes"]:
            continue

        # 优先使用规范化后的枚举值，规范化结果缺失时回退原始枚举值
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

        item_count = _enum_item_count(normalized)
        if row["field_type"] == "代码枚举类" and code_values == {"是", "否"}:
            row["flag_issues"].append(
                "代码枚举类字段的枚举值有且仅有'是'和'否'，应申报为标志类"
            )
            flagged += 1
        elif row["field_type"] == "标志类" and item_count > 2:
            row["flag_issues"].append(
                f"标志类字段的枚举值超过两项（实际{item_count}项），应申报为代码枚举类"
            )
            flagged += 1

    print(f"  发现 {flagged} 行字段类型与枚举值可能不一致")
    return {"rows": rows}


# ============================================================
# 节点 5: 汇总检查结果
# ============================================================

def combine_results_node(state: GraphState) -> dict:
    """汇总规则检查、业务含义检查、类型一致性检查、枚举规范化的结果，判定通过/不通过。"""
    print("\n=== 步骤 5/6: 汇总检查结果 ===")
    rows = state["rows"]

    semantic_map, duplicate_semantic_indices = build_row_result_map(
        state.get("semantic_results", [])
    )
    enum_map, duplicate_enum_indices = build_row_result_map(
        state.get("enum_results", [])
    )

    for row in rows:
        idx = row["index"]
        reasons = []

        # 规则检查问题
        if row["rule_issues"]:
            reasons.extend(row["rule_issues"])

        # 类型与枚举值一致性问题
        if row["flag_issues"]:
            reasons.extend(row["flag_issues"])

        # 业务含义检查结果
        if idx in duplicate_semantic_indices:
            reasons.append("LLM返回重复结果，业务含义检查需人工复核")
        elif idx in semantic_map:
            sr = semantic_map[idx]
            row["is_meaningful"] = sr["is_meaningful"]
            row["meaning_reason"] = sr["reason"]
            if not sr["is_meaningful"]:
                reasons.append(row["meaning_reason"])
        else:
            # 未被 LLM 检查的行
            if not row["business_meaning"]:
                row["is_meaningful"] = True
                row["meaning_reason"] = ""
            else:
                # 业务定义非空但 LLM 未返回该行结果
                row["is_meaningful"] = True
                row["meaning_reason"] = "LLM未返回该行结果"
                reasons.append("LLM未返回该行结果，业务含义检查需人工复核")

        # 枚举值规范化结果
        if idx in duplicate_enum_indices:
            reasons.append("LLM返回重复结果，枚举值规范化需人工复核")
        elif idx in enum_map:
            er = enum_map[idx]
            if not er["has_codes"]:
                reasons.append("枚举值缺少代码，应填写'代码-码值'形式")
                row["normalized_enum"] = ""   # 保留原始枚举值输出
            else:
                row["normalized_enum"] = er["normalized"]
        elif row["enum_values"]:
            reasons.append("LLM未返回该行枚举值规范化结果，需人工复核")

        # 判定最终结果
        if reasons:
            row["check_result"] = "不通过"
            row["fail_reason"] = "\n".join(f"{i}. {r}" for i, r in enumerate(reasons, 1))
        else:
            row["check_result"] = "通过"
            row["fail_reason"] = ""

    passed = sum(1 for r in rows if r["check_result"] == "通过")
    print(f"  检查结果: 通过 {passed} 行，不通过 {len(rows) - passed} 行")
    return {"rows": rows}


# ============================================================
# 节点 5b: 软性检查（字段所属类型 + 枚举值数量/语义提示，汇总后执行）
# ============================================================

def soft_check_node(state: GraphState) -> dict:
    """检查字段所属类型，并提示枚举值数量或语义可疑（软性提醒）。

    仅检查依赖字段非空的记录，不依赖硬性检查是否通过：
      - 字段所属类型检查：非代码枚举类/标志类的通用语义类型提示；
      - 枚举值数量/语义提示：代码枚举类或标志类枚举值两项时由 LLM 判断。
    结果写入"软性检查结果"列，不影响"检查结果"列判定。
    """
    print("\n=== 步骤 5b/6: 软性检查（字段所属类型 + 枚举值唯一性 + 反义词）===")
    rows = state["rows"]

    rows_to_check = [
        {
            "row_index": r["index"],
            "中文字段名": r["field_name"],
            "业务定义": r["business_meaning"],
            "字段所属类型": r["field_type"],
        }
        for r in rows
        if r["field_name"]
        and r["business_meaning"]
        and r["field_type"]
        and r["field_type"] not in ("代码枚举类", "标志类")
    ]

    # 代码枚举类/标志类两项枚举值语义提示（软性提醒，LLM 判断）
    antonym_rows = [
        {
            "row_index": r["index"],
            "字段中文名": r["field_name"],
            "枚举值": r["normalized_enum"] or r["enum_values"],
        }
        for r in rows
        if r["field_name"]
        and r["field_type"] in ("代码枚举类", "标志类")
        and _enum_item_count(r["normalized_enum"] or r["enum_values"]) == 2
    ]

    print(f"  共 {len(rows_to_check)} 行需要检查字段所属类型，"
          f"{len(antonym_rows)} 行需要检查枚举值反义词")
    type_sent_indices = {r["row_index"] for r in rows_to_check}
    antonym_sent_indices = {r["row_index"] for r in antonym_rows}
    duplicate_type_indices = set()
    duplicate_antonym_indices = set()
    try:
        results = []
        result_map = {}
        if rows_to_check:
            llm = get_llm()
            results = check_field_types(llm, rows_to_check)
            result_map, duplicate_type_indices = build_row_result_map(results)

        antonym_map = {}
        if antonym_rows:
            llm = get_llm()
            antonym_map, duplicate_antonym_indices = build_row_result_map(
                check_enum_antonyms(llm, antonym_rows)
            )

        for row in rows:
            notes = []
            r = result_map.get(row["index"])
            if row["index"] in duplicate_type_indices:
                notes.append("LLM返回重复结果，字段所属类型检查需人工复核")
            elif r is None and row["index"] in type_sent_indices:
                notes.append("LLM未返回该行结果，字段所属类型检查需人工复核")
            elif r is not None and not r["is_correct"]:
                notes.append(
                    f"因为{r['reason']}，当前字段所属类型可能错误，"
                    f"应为{r['correct_type']}，请联系业务确认"
                )
            # 枚举值仅有一项提示（软性提醒，不依赖 LLM）
            # 优先用规范化后的枚举值，无规范化结果时回退原始枚举值
            enum_vals = row["normalized_enum"] or row["enum_values"]
            if enum_vals and _enum_item_count(enum_vals) == 1:
                if row["field_type"] == "标志类":
                    notes.append(
                        f"标志类应有两项语义相反的取值，当前仅有'{enum_vals}'，请人工确认"
                    )
                else:
                    notes.append(
                        f"枚举值仅有一个取值'{enum_vals}'，"
                        f"请确认该字段是否为枚举类型或需补充其他枚举值"
                    )
            if enum_vals and _enum_item_count(enum_vals) > 1:
                enum_items = [
                    item.strip()
                    for item in str(enum_vals).split(";")
                    if item.strip()
                ]
                code_parts = [
                    item.partition("-")[0].strip() if "-" in item else ""
                    for item in enum_items
                ]
                value_parts = [
                    item.partition("-")[2].strip() if "-" in item else item
                    for item in enum_items
                ]
                duplicate_codes = [
                    code for code in set(code_parts) if code
                    and code_parts.count(code) > 1
                ]
                duplicate_values = [
                    value for value in set(value_parts) if value
                    and value_parts.count(value) > 1
                ]
                if duplicate_codes:
                    notes.append(
                        f"枚举码重复：{'、'.join(duplicate_codes)}出现多次，请人工确认"
                    )
                if duplicate_values:
                    notes.append(
                        f"枚举码值重复：{'、'.join(duplicate_values)}出现多次，请人工确认"
                    )
            # 枚举值两项语义提示（软性提醒，LLM 判断）
            ar = antonym_map.get(row["index"])
            if row["index"] in duplicate_antonym_indices:
                notes.append("LLM返回重复结果，枚举值反义词检查需人工复核")
            elif ar is None and row["index"] in antonym_sent_indices:
                notes.append("LLM未返回该行结果，枚举值反义词检查需人工复核")
            elif (
                ar is not None
                and row["field_type"] == "代码枚举类"
                and ar["is_antonym"]
            ):
                notes.append(
                    f"枚举值两项（{enum_vals}）为反义词，"
                    f"该字段可能应为标志类而非代码枚举类，请联系业务确认"
                )
            elif (
                ar is not None
                and row["field_type"] == "标志类"
                and not ar["is_antonym"]
            ):
                notes.append(
                    f"枚举值两项（{enum_vals}）不能理解为反义词或'是/否'关系，"
                    f"该字段可能不是标志类，请联系业务确认"
                )
            unique_notes = list(dict.fromkeys(notes))
            row["soft_check_result"] = "\n".join(
                f"{i}. {n}" for i, n in enumerate(unique_notes, 1)
            )

        print(f"  软性检查完成：字段所属类型 {len(results)} 条结果，"
              f"枚举值反义词 {len(antonym_map)} 条结果")
        return {"soft_check_results": results}
    except Exception as e:
        print(f"  [WARNING] LLM 软性检查失败: {e}")
        print("  跳过软性检查，仅输出规则检查结果")
        for row in rows:
            if row["index"] in type_sent_indices:
                row["soft_check_result"] = "LLM软性检查未执行，字段所属类型需人工复核"
            elif row["index"] in antonym_sent_indices:
                row["soft_check_result"] = "LLM软性检查未执行，枚举值反义词需人工复核"
        return {"soft_check_results": []}


# ============================================================
# 节点 6: 写入 Excel
# ============================================================

def write_excel_node(state: GraphState) -> dict:
    """将检查结果写入输出 Excel。"""
    print("\n=== 步骤 6/6: 写入结果 Excel ===")
    write_excel(state["output_file"], state["rows"], state["input_file"])
    return {}
