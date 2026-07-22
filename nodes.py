"""LangGraph 节点定义。

图结构：
  START
    ↓
  load_excel  -- 读取 Excel，初始化 RowData
    ↓
  check_basic -- 规则检查：必填列是否为空
    ↓
  ┌─────────────────┐
  │ check_semantic   │  (并行) LLM 检查业务含义
  │ normalize_enum   │  (并行) LLM 规范化枚举值
  └────────┬────────┘
           ↓
  combine_results -- 汇总所有检查结果，判定通过/不通过
    ↓
  write_excel -- 输出结果 Excel
    ↓
  END
"""

from state import GraphState, RowData
from excel_utils import read_excel, write_excel
from llm_client import get_llm, check_business_meaning, normalize_enum_values


# ============================================================
# 节点 1: 加载 Excel
# ============================================================

def load_excel_node(state: GraphState) -> dict:
    """读取输入 Excel，初始化 RowData 列表。"""
    print("\n=== 步骤 1/5: 加载 Excel ===")
    rows = read_excel(state["input_file"])
    return {"rows": rows, "semantic_results": [], "enum_results": []}


# ============================================================
# 节点 2: 基础规则检查（空值检测）
# ============================================================

def check_basic_node(state: GraphState) -> dict:
    """规则检查：字段中文名、字段所属类型、业务含义是否为空。"""
    print("\n=== 步骤 2/5: 基础规则检查（空值检测）===")
    rows = state["rows"]
    empty_count = 0

    for row in rows:
        empty_fields = []
        if not row["field_name"]:
            empty_fields.append("字段中文名")
        if not row["field_type"]:
            empty_fields.append("字段所属类型")
        if not row["business_meaning"]:
            empty_fields.append("业务含义")

        if empty_fields:
            row["is_empty_issue"] = True
            row["empty_details"] = f"以下列为空: {', '.join(empty_fields)}"
            empty_count += 1
        else:
            row["is_empty_issue"] = False
            row["empty_details"] = ""

    print(f"  发现 {empty_count} 行存在空值问题")
    return {"rows": rows}


# ============================================================
# 节点 3a: LLM 业务含义检查（与节点3b并行执行）
# ============================================================

def check_semantic_node(state: GraphState) -> dict:
    """调用 LLM 批量检查业务含义是否有效。

    跳过业务含义为空的行（已在 check_basic 中标记）。
    """
    print("\n=== 步骤 3a/5: LLM 业务含义检查 ===")
    rows = state["rows"]

    # 筛选需要检查的行：业务含义非空
    rows_to_check = [
        {
            "row_index": r["index"],
            "字段中文名": r["field_name"],
            "业务含义": r["business_meaning"],
        }
        for r in rows
        if r["business_meaning"] and not r["is_empty_issue"]
    ]

    if not rows_to_check:
        print("  没有需要检查的行（业务含义均为空）")
        return {"semantic_results": []}

    print(f"  共 {len(rows_to_check)} 行需要检查业务含义")
    llm = get_llm()
    results = check_business_meaning(llm, rows_to_check)
    print(f"  业务含义检查完成，共 {len(results)} 条结果")
    return {"semantic_results": results}


# ============================================================
# 节点 3b: LLM 枚举值规范化（与节点3a并行执行）
# ============================================================

def normalize_enum_node(state: GraphState) -> dict:
    """调用 LLM 批量规范化枚举值。

    跳过枚举值为空的行。
    """
    print("\n=== 步骤 3b/5: LLM 枚举值规范化 ===")
    rows = state["rows"]

    # 筛选有枚举值的行
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
    llm = get_llm()
    results = normalize_enum_values(llm, rows_with_enum)
    print(f"  枚举值规范化完成，共 {len(results)} 条结果")
    return {"enum_results": results}


# ============================================================
# 节点 4: 汇总检查结果
# ============================================================

def combine_results_node(state: GraphState) -> dict:
    """汇总空值检查、业务含义检查、枚举规范化的结果，判定通过/不通过。"""
    print("\n=== 步骤 4/5: 汇总检查结果 ===")
    rows = state["rows"]

    # 将结果列表转为 dict 便于按 row_index 查找
    semantic_map = {r["row_index"]: r for r in state.get("semantic_results", [])}
    enum_map = {r["row_index"]: r for r in state.get("enum_results", [])}

    for row in rows:
        idx = row["index"]

        # 应用业务含义检查结果
        if idx in semantic_map:
            sr = semantic_map[idx]
            row["is_meaningful"] = sr["is_meaningful"]
            row["meaning_reason"] = sr["reason"]
        else:
            # 未被 LLM 检查的行（如业务含义为空），默认无效
            row["is_meaningful"] = False
            if row["is_empty_issue"] and not row["business_meaning"]:
                row["meaning_reason"] = "业务含义为空，无法进行语义检查"
            else:
                row["is_meaningful"] = True  # 其他情况默认通过

        # 应用枚举值规范化结果
        if idx in enum_map:
            er = enum_map[idx]
            row["normalized_enum"] = er["normalized"]
            row["enum_needs_normalization"] = er["needs_normalization"]

        # 判定最终结果
        reasons = []
        if row["is_empty_issue"]:
            reasons.append(row["empty_details"])
        if not row["is_meaningful"]:
            reasons.append(row["meaning_reason"])

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
