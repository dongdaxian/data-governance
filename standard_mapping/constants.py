"""落标处理 -- 常量定义。

包含字段类型、输入列名、输出列名、域类型正则匹配规则等。
域类型规则参考 data/域类型说明.xlsx。
"""

import re

# ============================================================
# 字段类型
# ============================================================

# 合法的字段所属类型（与 quality_check 一致）
VALID_FIELD_TYPES = ["数值类", "编码类", "代码枚举类", "日期时间类", "标志类", "文本类"]

# 本模块处理的非代码枚举类类型
NON_ENUM_TYPES = ["数值类", "编码类", "日期时间类", "标志类", "文本类"]

# ============================================================
# 输入列名（支持模糊匹配，与 quality_check 一致，增加数据示例列）
# ============================================================

INPUT_COLUMNS = {
    "field_name": ["字段中文名", "字段名称", "中文名", "字段名"],
    "field_type": ["字段所属类型", "字段类型", "所属类型", "类型"],
    "business_meaning": ["业务含义", "含义", "业务说明", "说明"],
    "enum_values": ["枚举值", "枚举", "码值", "代码值"],
    "data_example": ["数据示例", "示例", "样例", "数据样例"],
}

# ============================================================
# 输出新增列名
# ============================================================

COL_MAPPING_RESULT = "落标结果"
COL_SELECTED_STD_ID = "选中标准编号"
COL_SELECTED_STD_NAME = "选中标准名称"
COL_LLM_REASON = "LLM判断过程"

# ============================================================
# 域类型正则匹配规则（参考 data/域类型说明.xlsx）
# ============================================================

# 数字字符类：n..(x) 最大长度x，n!(x) 固定长度x
RE_N_VAR = re.compile(r"^n\.\.\((\d+)\)$")
RE_N_FIX = re.compile(r"^n!\((\d+)\)$")

# 字母类：a..(x) 最大长度x，a!(x) 固定长度x
RE_A_VAR = re.compile(r"^a\.\.\((\d+)\)$")
RE_A_FIX = re.compile(r"^a!\((\d+)\)$")

# 数字+字母类：an..(x) 最大长度x，an!(x) 固定长度x
RE_AN_VAR = re.compile(r"^an\.\.\((\d+)\)$")
RE_AN_FIX = re.compile(r"^an!\((\d+)\)$")

# 汉字+数字+字母类：anc..(x) 最大长度x，anc!(x) 固定长度x
RE_ANC_VAR = re.compile(r"^anc\.\.\((\d+)\)$")
RE_ANC_FIX = re.compile(r"^anc!\((\d+)\)$")

# 整数类：i(x) x位整数，i(x,y) x位整数y位小数
RE_I_INT = re.compile(r"^i\((\d+)\)$")
RE_I_DEC = re.compile(r"^i\((\d+),\s*(\d+)\)$")

# 日期时间类
RE_DATE = re.compile(r"^DATE$", re.IGNORECASE)
RE_TIME = re.compile(r"^TIME$", re.IGNORECASE)
RE_DATETIME = re.compile(r"^DATETIME$", re.IGNORECASE)
RE_TIMESTAMP = re.compile(r"^TIMESTAMP$", re.IGNORECASE)

# 汉字范围正则（用于冲突检测）
RE_CHINESE = re.compile(r"[\u4e00-\u9fff]")
# 数字正则
RE_DIGIT = re.compile(r"\d")
