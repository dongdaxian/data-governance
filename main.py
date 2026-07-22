"""数据质量检查 -- 入口脚本。

用法：
  python main.py --input 输入.xlsx --output 输出.xlsx

示例：
  python main.py --input sample_input.xlsx --output sample_output.xlsx
"""

import argparse
import sys
import os

from graph import build_graph


def main():
    parser = argparse.ArgumentParser(
        description="数据质量检查工具 -- 使用 GLM-5.2 + LangGraph 检查 Excel 数据质量"
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="输入 Excel 文件路径",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="输出 Excel 文件路径（默认在输入文件名后加 _output）",
    )
    args = parser.parse_args()

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


if __name__ == "__main__":
    main()
