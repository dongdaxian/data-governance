"""Excel 读取/写入工具。

读取：将 Excel 解析为 RowData 列表，支持列名模糊匹配。
  输入 Excel 格式：第1行合并表头"基本信息"，第2行列名，第3行+数据。
写入：在原始数据基础上追加三列检查结果，输出新 Excel。
  输出 Excel 格式：第1行合并表头（"基本信息" + "数管反馈"），第2行列名，第3行+数据。
"""

import pandas as pd
from openpyxl import load_workbook

from quality_check.constants import (
    INPUT_COLUMNS,
    COL_NORMALIZED_ENUM,
    COL_CHECK_RESULT,
    COL_FAIL_REASON,
)
from quality_check.state import RowData


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

    # 未匹配到的按位置取前4列
    fallback_order = ["field_name", "field_type", "business_meaning", "enum_values"]
    for i, key in enumerate(fallback_order):
        if key not in matched and i < len(actual_cols):
            matched[key] = actual_cols[i]

    return matched


def read_excel(file_path: str) -> list[RowData]:
    """读取 Excel 文件，返回 RowData 列表。

    输入 Excel 第1行为合并表头，第2行为列名，从第3行开始为数据。
    """
    df = pd.read_excel(file_path, header=1)
    col_map = _match_columns(df)

    rows: list[RowData] = []
    for idx, row in df.iterrows():
        rows.append(RowData(
            index=int(idx),
            field_name=str(row.get(col_map["field_name"], "") or "").strip(),
            field_type=str(row.get(col_map["field_type"], "") or "").strip(),
            business_meaning=str(row.get(col_map["business_meaning"], "") or "").strip(),
            enum_values=str(row.get(col_map["enum_values"], "") or "").strip(),
            # 初始化结果字段
            is_empty_issue=False,
            empty_details="",
            is_meaningful=True,
            meaning_reason="",
            normalized_enum="",
            enum_needs_normalization=False,
            check_result="",
            fail_reason="",
        ))

    print(f"已读取 {len(rows)} 行数据")
    print(f"  列映射: {col_map}")
    return rows


def write_excel(file_path: str, rows: list[RowData], input_file: str):
    """将检查结果写入 Excel。

    保留原始数据列，追加三列：规范化后的枚举值、检查结果、不通过原因。
    输出格式：第1行合并表头（"基本信息" + "数管反馈"），第2行列名，第3行+数据。
    """
    # 读取原始 Excel（跳过合并表头行，从第2行开始）
    df = pd.read_excel(input_file, header=1)

    # 按 rows 的 index 顺序追加结果列
    sorted_rows = sorted(rows, key=lambda r: r["index"])

    df[COL_NORMALIZED_ENUM] = [
        r["normalized_enum"] if r["enum_needs_normalization"] else ""
        for r in sorted_rows
    ]
    df[COL_CHECK_RESULT] = [r["check_result"] for r in sorted_rows]
    df[COL_FAIL_REASON] = [r["fail_reason"] for r in sorted_rows]

    df.to_excel(file_path, index=False)

    # 在第1行插入合并表头："基本信息"（前4列）+ "数管反馈"（后3列）
    wb = load_workbook(file_path)
    ws = wb.active
    ws.insert_rows(1)
    total_cols = len(df.columns)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=4)
    ws.cell(row=1, column=1, value="基本信息")
    ws.merge_cells(start_row=1, start_column=5, end_row=1, end_column=total_cols)
    ws.cell(row=1, column=5, value="数管反馈")
    wb.save(file_path)

    print(f"结果已写入: {file_path}")

    # 打印统计
    total = len(sorted_rows)
    passed = sum(1 for r in sorted_rows if r["check_result"] == "通过")
    failed = total - passed
    print(f"  总计: {total} 行 | 通过: {passed} | 不通过: {failed}")
