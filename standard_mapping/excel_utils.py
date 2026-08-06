"""Excel 读取/写入工具。

读取：将 Excel 解析为 FieldToMap 列表，支持列名模糊匹配。
  输入 Excel 格式：第1行合并表头"基本信息"，第2行列名，第3行+数据。
写入：在原始数据基础上追加五列落标结果，输出新 Excel。
  输出 Excel 格式：第1行合并表头（"基本信息" + "落标结果"），第2行列名，第3行+数据。
"""

import pandas as pd
from openpyxl import load_workbook

from standard_mapping.constants import (
    INPUT_COLUMNS,
    COL_MAPPING_RESULT,
    COL_SELECTED_STD_ID,
    COL_SELECTED_STD_NAME,
    COL_LLM_REASON,
)
from standard_mapping.state import FieldToMap


def _match_columns(df: pd.DataFrame) -> dict[str, str]:
    """模糊匹配 Excel 列名到内部字段名。

    Returns:
        {"field_name": "实际列名", "field_type": "...", ...}
    """
    matched = {}
    actual_cols = [str(c) for c in df.columns]

    for internal_name, keywords in INPUT_COLUMNS.items():
        for col in actual_cols:
            if any(kw in col for kw in keywords):
                matched[internal_name] = col
                break

    # 未匹配到的前4列按位置兜底
    fallback_order = ["field_name", "field_type", "business_meaning", "enum_values"]
    for i, key in enumerate(fallback_order):
        if key not in matched and i < len(actual_cols):
            matched[key] = actual_cols[i]

    return matched


def read_excel(file_path: str) -> list[FieldToMap]:
    """读取 Excel 文件，返回 FieldToMap 列表。

    输入 Excel 第1行为合并表头，第2行为列名，从第3行开始为数据。
    如果存在"数据示例"列则读取，否则该字段为空。
    """
    df = pd.read_excel(file_path, header=1)
    col_map = _match_columns(df)

    rows: list[FieldToMap] = []
    for idx, row in df.iterrows():
        rows.append(FieldToMap(
            index=int(idx),
            field_name=str(row.get(col_map["field_name"], "") or "").strip(),
            field_type=str(row.get(col_map["field_type"], "") or "").strip(),
            business_meaning=str(row.get(col_map["business_meaning"], "") or "").strip(),
            enum_values=str(row.get(col_map["enum_values"], "") or "").strip(),
            data_example=str(row.get(col_map["data_example"], "") or "").strip() if "data_example" in col_map else "",
            # 初始化结果字段
            candidates=[],
            domain_check_details="",
            mapping_result="",
            selected_std_id="",
            selected_std_name="",
            llm_reason="",
        ))

    print(f"已读取 {len(rows)} 行数据")
    print(f"  列映射: {col_map}")
    return rows


def write_excel(file_path: str, rows: list[FieldToMap], input_file: str):
    """将落标结果写入 Excel。

    保留原始数据列，追加四列：落标结果、选中标准编号、选中标准名称、LLM判断过程。
    输出格式：第1行合并表头（"基本信息" + "落标结果"），第2行列名，第3行+数据。
    """
    # 读取原始 Excel（跳过合并表头行，从第2行开始）
    df = pd.read_excel(input_file, header=1)
    orig_col_count = len(df.columns)

    # 按 rows 的 index 顺序追加结果列
    sorted_rows = sorted(rows, key=lambda r: r["index"])

    df[COL_MAPPING_RESULT] = [r["mapping_result"] for r in sorted_rows]
    df[COL_SELECTED_STD_ID] = [r["selected_std_id"] for r in sorted_rows]
    df[COL_SELECTED_STD_NAME] = [r["selected_std_name"] for r in sorted_rows]
    df[COL_LLM_REASON] = [r["llm_reason"] for r in sorted_rows]

    df.to_excel(file_path, index=False)

    # 在第1行插入合并表头："基本信息"（原始列）+ "落标结果"（新增4列）
    wb = load_workbook(file_path)
    ws = wb.active
    ws.insert_rows(1)
    total_cols = len(df.columns)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=orig_col_count)
    ws.cell(row=1, column=1, value="基本信息")
    ws.merge_cells(start_row=1, start_column=orig_col_count + 1, end_row=1, end_column=total_cols)
    ws.cell(row=1, column=orig_col_count + 1, value="落标结果")
    wb.save(file_path)

    print(f"结果已写入: {file_path}")

    # 打印统计
    total = len(sorted_rows)
    reuse = sum(1 for r in sorted_rows if r["mapping_result"] == "复用已有标准")
    reuse_ext = sum(1 for r in sorted_rows if r["mapping_result"] == "复用已有标准但扩展业务定义")
    new_std = sum(1 for r in sorted_rows if r["mapping_result"] == "新增标准")
    print(f"  总计: {total} 行 | 复用已有标准: {reuse} | 复用但扩展: {reuse_ext} | 新增标准: {new_std}")
