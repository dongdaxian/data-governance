"""数据治理工具 -- 统一入口。

用法：
  python main.py quality-check --input 输入.xlsx --output 输出.xlsx
  python main.py standard-mapping --input 输入.xlsx --output 输出.xlsx
  python main.py standard-maintenance --input 输入.xlsx --output 输出.xlsx

示例：
  python main.py quality-check --input data/qc_input.xlsx --output data/qc_output.xlsx
"""

import argparse
import sys
import os


def run_quality_check(args):
    """运行数据质量检查。"""
    from quality_check.graph import build_graph

    input_file = args.input
    if not os.path.exists(input_file):
        print(f"错误：输入文件不存在: {input_file}")
        sys.exit(1)

    output_file = args.output
    if output_file is None:
        base, ext = os.path.splitext(input_file)
        output_file = f"{base}_output{ext}"

    print("=" * 60)
    print("  数据质量检查工具")
    print(f"  输入文件: {input_file}")
    print(f"  输出文件: {output_file}")
    print("=" * 60)

    # 构建并执行工作流
    app = build_graph()

    initial_state = {
        "rows": [],
        "input_file": input_file,
        "output_file": output_file,
        "semantic_results": [],
        "enum_results": [],
    }

    app.invoke(initial_state, config={"recursion_limit": 100})

    print("\n" + "=" * 60)
    print("  检查完成！")
    print(f"  结果文件: {output_file}")
    print("=" * 60)


def run_standard_mapping(args):
    """运行落标处理。"""
    from standard_mapping.graph import build_graph

    input_file = args.input
    if not os.path.exists(input_file):
        print(f"错误：输入文件不存在: {input_file}")
        sys.exit(1)

    output_file = args.output
    if output_file is None:
        base, ext = os.path.splitext(input_file)
        output_file = f"{base}_output{ext}"

    print("=" * 60)
    print("  落标处理工具")
    print(f"  输入文件: {input_file}")
    print(f"  输出文件: {output_file}")
    print("=" * 60)

    # 构建并执行工作流
    app = build_graph()

    initial_state = {
        "rows": [],
        "input_file": input_file,
        "output_file": output_file,
        "domain_results": [],
        "selection_results": [],
        "include_candidates": True,
    }

    app.invoke(initial_state, config={"recursion_limit": 100})

    print("\n" + "=" * 60)
    print("  落标处理完成！")
    print(f"  结果文件: {output_file}")
    print("=" * 60)


def run_standard_maintenance(args):
    """运行标准维护。"""
    print("标准维护模块开发中...")


def main():
    parser = argparse.ArgumentParser(description="数据治理工具")
    subparsers = parser.add_subparsers(dest="command", help="选择功能模块")

    # quality-check
    qc_parser = subparsers.add_parser("quality-check", help="数据质量检查")
    qc_parser.add_argument("--input", "-i", required=True, help="输入 Excel 文件路径")
    qc_parser.add_argument("--output", "-o", default=None, help="输出 Excel 文件路径（默认在输入文件名后加 _output）")

    # standard-mapping
    sm_parser = subparsers.add_parser("standard-mapping", help="落标处理")
    sm_parser.add_argument("--input", "-i", required=True, help="输入 Excel 文件路径")
    sm_parser.add_argument("--output", "-o", default=None, help="输出 Excel 文件路径（默认在输入文件名后加 _output）")
    sm_parser.add_argument(
        "--include-candidates",
        action="store_true",
        help="输出中附带候选标准及得分明细列（测试/调试用，默认关闭）",
    )

    # standard-maintenance
    stm_parser = subparsers.add_parser("standard-maintenance", help="标准维护")
    stm_parser.add_argument("--input", "-i", required=True, help="输入 Excel 文件路径")
    stm_parser.add_argument("--output", "-o", default=None, help="输出 Excel 文件路径（默认在输入文件名后加 _output）")

    args = parser.parse_args()
    if args.command == "quality-check":
        run_quality_check(args)
    elif args.command == "standard-mapping":
        run_standard_mapping(args)
    elif args.command == "standard-maintenance":
        run_standard_maintenance(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
