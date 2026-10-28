# -*- coding: utf-8 -*-
"""标准维护 LangGraph 节点定义。

图结构：
  START
    ↓
  load      -- 读取 Excel，加载全部字典申请单字段
    ↓
  normalize -- 步骤2：LLM 规范化中文字段名（不规范才改，如"数据权限代码KEY值5"→"权限编号"）
    ↓
  generate  -- 步骤3：LLM 依据规范化名称生成业务定义
    ↓
  merge     -- 步骤4：LLM 将生成定义与原始定义对照，漏掉语义补充整合，已包含则跳过
    ↓
  write     -- 步骤5：输出"变更标准"组（输入后附加6列，标准编号留空）
    ↓
  END
"""

from config import WRITE_INTERVAL_ROWS

from standard_maintenance.state import MaintenanceGraphState
from standard_maintenance.excel_utils import read_excel, write_excel
from standard_maintenance.llm import (
    normalize_field_names,
    generate_definitions,
    merge_definitions,
)
from common.llm_client import get_llm, build_row_result_map, append_module_log


# ============================================================
# 节点 1: 加载 Excel
# ============================================================

def load_node(state: MaintenanceGraphState) -> dict:
    """读取输入 Excel，加载全部字典申请单字段。"""
    print("\n=== 步骤 1/5: 加载 Excel ===")
    rows = read_excel(state["input_file"])
    print(f"  加载完成: {len(rows)} 行")
    return {"rows": rows}


# ============================================================
# 节点 2: 中文字段名规范化（步骤2）
# ============================================================

def normalize_node(state: MaintenanceGraphState) -> dict:
    """调用 LLM 规范化中文字段名。

    - 规范化结果缺失/重复的行回退原始名，warning 提示。
    - LLM 调用整体失败：warning 后全部回退原始值，不中断流程。
    - 日志记录"原名称 -> 规范化名称（reasoning）"。
    """
    print("\n=== 步骤 2/5: LLM 字段名规范化 ===")
    rows = state["rows"]
    llm = get_llm()

    try:
        results = normalize_field_names(llm, [{
            "row_index": r["index"],
            "field_name": r["field_name"],
            "business_meaning": r["business_meaning"],
        } for r in rows])
    except Exception as e:
        print(f"  [WARNING] 字段名规范化 LLM 调用失败，全部使用原始字段名: {e}")
        for r in rows:
            r["normalized_name"] = r["field_name"]
        return {"rows": rows}

    result_map, duplicate_indices = build_row_result_map(results)
    for r in rows:
        idx = r["index"]
        if idx in duplicate_indices or idx not in result_map:
            print(f"  [WARNING] 行 {idx} 字段名规范化结果缺失/重复，使用原始值")
            r["normalized_name"] = r["field_name"]
            continue
        item = result_map[idx]
        normalized = item.get("normalized_name", "").strip()
        changed = item.get("changed", False)
        reasoning = item.get("reasoning", "")
        if not normalized:
            r["normalized_name"] = r["field_name"]
            continue
        r["normalized_name"] = normalized
        if changed:
            msg = (f"  行 {idx} 字段名规范化: '{r['field_name']}' -> '{normalized}' "
                   f"（reasoning: {reasoning}）")
            print(msg)
            append_module_log("standard_maintenance", msg + "\n")

    return {"rows": rows}


# ============================================================
# 节点 3: 业务定义生成（步骤3）
# ============================================================

def generate_node(state: MaintenanceGraphState) -> dict:
    """调用 LLM 依据规范化后的中文字段名生成业务定义。

    - 结果缺失/重复的行标记"LLM 未返回，需人工复核"（生成定义留空）。
    - LLM 调用整体失败：warning 后全部留空并标记，不中断流程。
    """
    print("\n=== 步骤 3/5: LLM 业务定义生成 ===")
    rows = state["rows"]
    llm = get_llm()

    try:
        results = generate_definitions(llm, [{
            "row_index": r["index"],
            "field_name": r["normalized_name"],
            "field_type": r["field_type"],
            "enum_values": r["enum_values"],
            "business_meaning": r["business_meaning"],
        } for r in rows])
    except Exception as e:
        print(f"  [WARNING] 业务定义生成 LLM 调用失败，全部标记需人工复核: {e}")
        for r in rows:
            r["generated_definition"] = ""
            r["definition_reason"] = f"LLM 调用失败: {e}"
        return {"rows": rows}

    result_map, duplicate_indices = build_row_result_map(results)
    for r in rows:
        idx = r["index"]
        if idx in duplicate_indices or idx not in result_map:
            print(f"  [WARNING] 行 {idx} 业务定义生成结果缺失/重复，标记需人工复核")
            r["generated_definition"] = ""
            r["definition_reason"] = "LLM 调用成功但该行结果缺失/重复，需人工复核"
            continue
        item = result_map[idx]
        definition = item.get("definition", "").strip()
        if not definition:
            print(f"  [WARNING] 行 {idx} 业务定义生成为空，标记需人工复核")
            r["generated_definition"] = ""
            r["definition_reason"] = "LLM 返回空定义，需人工复核"
            continue
        r["generated_definition"] = definition

    return {"rows": rows}


# ============================================================
# 节点 4: 业务定义对照整合（步骤4）
# ============================================================

def merge_node(state: MaintenanceGraphState) -> dict:
    """调用 LLM 将生成定义与原始定义对照，漏掉语义补充整合，已包含则跳过。

    - 生成定义为空的行（步骤3已标记需复核）跳过整合，最终定义留空，沿用复核标记。
    - 结果缺失/重复的行标记"LLM 未返回，需人工复核"。
    - LLM 调用整体失败：warning 后全部标记需人工复核，不中断流程。
    """
    print("\n=== 步骤 4/5: LLM 业务定义对照整合 ===")
    rows = state["rows"]
    llm = get_llm()

    pending = [r for r in rows if not r["generated_definition"]]
    if pending:
        print(f"  跳过 {len(pending)} 行（步骤3生成定义缺失，已标记需人工复核）")

    targets = [r for r in rows if r["generated_definition"]]
    if not targets:
        return {"rows": rows}

    try:
        results = merge_definitions(llm, [{
            "row_index": r["index"],
            "generated_definition": r["generated_definition"],
            "original_definition": r["business_meaning"],
        } for r in targets])
    except Exception as e:
        print(f"  [WARNING] 业务定义整合 LLM 调用失败，全部标记需人工复核: {e}")
        for r in targets:
            r["final_definition"] = ""
            r["definition_reason"] = f"LLM 调用失败: {e}"
        return {"rows": rows}

    result_map, duplicate_indices = build_row_result_map(results)
    for r in targets:
        idx = r["index"]
        if idx in duplicate_indices or idx not in result_map:
            print(f"  [WARNING] 行 {idx} 业务定义整合结果缺失/重复，标记需人工复核")
            r["final_definition"] = ""
            r["definition_reason"] = "LLM 调用成功但该行结果缺失/重复，需人工复核"
            continue
        item = result_map[idx]
        final_def = item.get("final_definition", "").strip()
        if not final_def:
            print(f"  [WARNING] 行 {idx} 业务定义整合为空，标记需人工复核")
            r["final_definition"] = ""
            r["definition_reason"] = "LLM 返回空定义，需人工复核"
            continue
        r["final_definition"] = final_def
        if item.get("merged", False):
            msg = (f"  行 {idx} 业务定义补充整合: 生成='{r['generated_definition']}' | "
                   f"最终='{final_def}'（reasoning: {item.get('reasoning', '')}）")
            print(msg)
            append_module_log("standard_maintenance", msg + "\n")

    return {"rows": rows}


# ============================================================
# 节点 5: 写入结果 Excel
# ============================================================

def write_node(state: MaintenanceGraphState) -> dict:
    """输出"变更标准"组：输入原列后附加6列（标准编号留空）。

    按 WRITE_INTERVAL_ROWS 行一组处理，每完成一组即增量写盘输出文件，
    避免大输入时等待全部行处理完才看到结果。
    """
    print("\n=== 步骤 5/5: 写入结果 Excel ===")
    rows = state["rows"]

    for chunk_start in range(0, len(rows), WRITE_INTERVAL_ROWS):
        chunk = rows[chunk_start:chunk_start + WRITE_INTERVAL_ROWS]
        batch_no = chunk_start // WRITE_INTERVAL_ROWS + 1
        print(f"  --- 批次 {batch_no}（输入第 {chunk_start + 1}-{chunk_start + len(chunk)} 行）---")
        # 增量写盘：首组新建文件，后续组追加填充（只写当前批次行）
        write_excel(
            state["output_file"],
            chunk,
            state["input_file"],
            append=chunk_start > 0,
        )

    return {}
