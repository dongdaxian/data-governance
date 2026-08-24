# -*- coding: utf-8 -*-
"""模块回归测试：以 test/<模块>/input.xlsx 为输入运行模块，
将本次实际输出与标准答案 test/<模块>/output.xlsx 的结论列逐格比对。

用法（在项目根目录执行，建议使用 data-gov 环境）：
  python test/run_tests.py                     # 测试全部模块
  python test/run_tests.py -m quality_check    # 只测质检模块
  python test/run_tests.py -m standard_mapping # 只测落标模块

目录约定：
  test/<模块>/input.xlsx          测试输入
  test/<模块>/output.xlsx         标准答案
  test/<模块>/actual_output.xlsx  本次实际输出（自动生成，已加入 .gitignore）

比对规则：
  - 只比对各模块的判定结论列：
      quality_check:     检查结果
      standard_mapping:  落标结果
  - 其余列（LLM 自由文本、向量检索浮点得分等）不参与比对
  - 比对前做值归一化：NaN/空值视为空串，整数值浮点转整数，去除首尾空白
"""

import argparse
import math
import os
import subprocess
import sys

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 模块测试配置
MODULES = {
    "quality_check": {
        "command": "quality-check",
        "extra_args": [],
        # 只比对判定结论列，其余列（LLM 自由文本等）不参与比对
        "compare_columns": ["检查结果"],
    },
    "standard_mapping": {
        "command": "standard-mapping",
        # 标准答案 output.xlsx 含"候选标准及得分"列，需带该参数生成
        "extra_args": ["--include-candidates"],
        # 只比对判定结论列，其余列（LLM 自由文本、浮点得分等）不参与比对
        "compare_columns": ["落标结果"],
    },
}

MAX_DIFF_SHOW = 20  # 最多展示的差异条数
MAX_VALUE_SHOW = 60  # 差异值截断长度


def normalize(v) -> str:
    """单元格值归一化，消除 NaN/空串/浮点整数的表示差异。"""
    if v is None:
        return ""
    if isinstance(v, float):
        if math.isnan(v):
            return ""
        if v.is_integer():
            return str(int(v))
        return str(v)
    s = str(v).strip()
    if s.lower() in ("nan", "none", "nat"):
        return ""
    return s


def _short(s: str) -> str:
    """差异展示时截断过长内容。"""
    return s if len(s) <= MAX_VALUE_SHOW else s[:MAX_VALUE_SHOW] + "..."


def run_module(cfg, input_file, actual_file) -> int:
    """调用 main.py 运行被测模块，返回退出码。"""
    cmd = [
        sys.executable,
        os.path.join(PROJECT_ROOT, "main.py"),
        cfg["command"],
        "--input", input_file,
        "--output", actual_file,
    ] + cfg["extra_args"]
    print(f"  运行: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=PROJECT_ROOT).returncode


def compare(actual_file, expected_file, compare_columns):
    """逐格比对实际输出与标准答案的指定结论列。

    Returns:
        (差异列表, 统计信息)
    """
    df_a = pd.read_excel(actual_file, header=1)
    df_e = pd.read_excel(expected_file, header=1)

    cols_e = [str(c) for c in df_e.columns]
    cols_a = [str(c) for c in df_a.columns]

    diffs = []
    compared_cols = 0

    if len(df_a) != len(df_e):
        diffs.append(f"行数不一致: 期望 {len(df_e)} 行, 实际 {len(df_a)} 行")

    n = min(len(df_a), len(df_e))

    for col in compare_columns:
        if col not in cols_e:
            diffs.append(f"标准答案缺少列: '{col}'")
            continue
        if col not in cols_a:
            diffs.append(f"实际输出缺少列: '{col}'")
            continue
        compared_cols += 1
        for i in range(n):
            ev = normalize(df_e[col].iloc[i])
            av = normalize(df_a[col].iloc[i])
            if ev != av:
                # 输入文件第 2 行是列名、第 3 行起是数据
                diffs.append(
                    f"第 {i + 1} 条数据(Excel 第 {i + 3} 行) 列 '{col}': "
                    f"期望 [{_short(ev)}] 实际 [{_short(av)}]"
                )

    stats = {
        "rows": len(df_e),
        "compared_cols": compared_cols,
        "total_cols": len(compare_columns),
    }
    return diffs, stats


def test_module(name: str) -> bool:
    """运行单个模块的测试，返回是否通过。"""
    cfg = MODULES[name]
    tdir = os.path.join(PROJECT_ROOT, "test", name)
    input_file = os.path.join(tdir, "input.xlsx")
    expected_file = os.path.join(tdir, "output.xlsx")
    actual_file = os.path.join(tdir, "actual_output.xlsx")

    print("=" * 60)
    print(f"[{name}]")

    missing = [f for f in (input_file, expected_file) if not os.path.exists(f)]
    if missing:
        print(f"  ✗ 缺少测试文件: {missing}")
        return False

    rc = run_module(cfg, input_file, actual_file)
    if rc != 0:
        print(f"  ✗ 模块运行失败 (退出码 {rc})")
        return False

    diffs, stats = compare(actual_file, expected_file, cfg["compare_columns"])

    print(f"  比对: {stats['rows']} 行 × {stats['compared_cols']}/{stats['total_cols']} 列")

    if not diffs:
        print("  ✓ 与标准答案一致")
        return True

    print(f"  ✗ 发现 {len(diffs)} 处不一致:")
    for d in diffs[:MAX_DIFF_SHOW]:
        print(f"    - {d}")
    if len(diffs) > MAX_DIFF_SHOW:
        print(f"    ... 其余 {len(diffs) - MAX_DIFF_SHOW} 处略")
    return False


def main():
    parser = argparse.ArgumentParser(description="模块回归测试：实际输出 vs 标准答案")
    parser.add_argument(
        "-m", "--module", choices=sorted(MODULES),
        help="只测试指定模块（默认全部）",
    )
    args = parser.parse_args()

    names = [args.module] if args.module else list(MODULES)
    results = {}
    for name in names:
        results[name] = test_module(name)

    print("\n" + "=" * 60)
    print("测试汇总:")
    for name, ok in results.items():
        print(f"  {'✓' if ok else '✗'} {name}")

    failed = [n for n, ok in results.items() if not ok]
    if failed:
        print(f"共 {len(failed)}/{len(results)} 个模块未通过")
        sys.exit(1)
    print(f"全部 {len(results)} 个模块通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
