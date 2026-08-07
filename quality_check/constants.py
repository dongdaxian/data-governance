# -*- coding: utf-8 -*-
"""数据质量检查 -- 常量定义。

包含输入列名、域类型正则规则、域类型白名单、输出列名等。
域类型规则参考 data/域类型说明.xlsx。
"""

import re

# ============================================================
# 字段类型
# ============================================================

# 合法的字段所属类型
VALID_FIELD_TYPES = ["数值类", "编码类", "代码枚举类", "日期时间类", "标志类", "文本类"]

# 非代码枚举类类型
NON_ENUM_TYPES = ["数值类", "编码类", "日期时间类", "标志类", "文本类"]

# ============================================================
# 输入列名（支持模糊匹配）
# ============================================================

INPUT_COLUMNS = {
    "table_name": ["中文表名(必填)"],
    "field_name": ["中文字段名(必填)"],
    "field_type": ["字段所属类型(必填)"],
    "domain_type": ["域类型(必填)"],
    "data_example": ["数据示例(必填)"],
    "is_enum": ["是否枚举(必填)"],
    "business_meaning": ["业务定义(必填)"],
    "enum_values": ["枚举值(选填)"],
}

# ============================================================
# 输出列名（与申请单模板一致）
# ============================================================

COL_FORMATTED_ENUM = "格式化枚举值"
COL_CHECK_RESULT = "检查结果"
COL_FAIL_REASON = "说明"

# ============================================================
# 域类型正则规则
# ============================================================

# 数值类
RE_I_INT = re.compile(r"^i\((\d+)\)$")
RE_I_DEC = re.compile(r"^i\((\d+),\s*(\d+)\)$")

# 数字字符类
RE_N_VAR = re.compile(r"^n\.\.\((\d+)\)$")
RE_N_FIX = re.compile(r"^n!\((\d+)\)$")
RE_N_VAR_NOLIMIT = re.compile(r"^n\.\.\(\)$")

# 字母+特殊符号类
RE_A_VAR = re.compile(r"^a\.\.\((\d+)\)$")
RE_A_FIX = re.compile(r"^a!\((\d+)\)$")
RE_A_VAR_NOLIMIT = re.compile(r"^a\.\.\(\)$")

# 数字+字母+特殊符号类
RE_AN_VAR = re.compile(r"^an\.\.\((\d+)\)$")
RE_AN_FIX = re.compile(r"^an!\((\d+)\)$")
RE_AN_VAR_NOLIMIT = re.compile(r"^an\.\.\(\)$")

# 汉字+数字+字母+特殊符号类
RE_ANC_VAR = re.compile(r"^anc\.\.\((\d+)\)$")
RE_ANC_FIX = re.compile(r"^anc!\((\d+)\)$")
RE_ANC_VAR_NOLIMIT = re.compile(r"^anc\.\.\(\)$")

# 纯汉字类
RE_C_VAR = re.compile(r"^c\.\.\((\d+)\)$")
RE_C_FIX = re.compile(r"^c!\((\d+)\)$")
RE_C_VAR_NOLIMIT = re.compile(r"^c\.\.\(\)$")

# 数字+汉字类
RE_NC_VAR = re.compile(r"^nc\.\.\((\d+)\)$")
RE_NC_FIX = re.compile(r"^nc!\((\d+)\)$")
RE_NC_VAR_NOLIMIT = re.compile(r"^nc\.\.\(\)$")

# 字母+汉字类
RE_AC_VAR = re.compile(r"^ac\.\.\((\d+)\)$")
RE_AC_FIX = re.compile(r"^ac!\((\d+)\)$")
RE_AC_VAR_NOLIMIT = re.compile(r"^ac\.\.\(\)$")

# 日期时间类
RE_DATE = re.compile(r"^DATE$", re.IGNORECASE)
RE_TIME = re.compile(r"^TIME$", re.IGNORECASE)
RE_DATETIME = re.compile(r"^DATETIME$", re.IGNORECASE)
RE_TIMESTAMP = re.compile(r"^TIMESTAMP$", re.IGNORECASE)
RE_TIME_P = re.compile(r"^TIME\((\d+)\)$", re.IGNORECASE)
RE_DATETIME_P = re.compile(r"^DATETIME\((\d+)\)$", re.IGNORECASE)
RE_TIMESTAMP_P = re.compile(r"^TIMESTAMP\((\d+)\)$", re.IGNORECASE)

# 字符检测正则
RE_CHINESE = re.compile(r"[\u4e00-\u9fff]")
RE_DIGIT = re.compile(r"[0-9]")
RE_LETTER = re.compile(r"[a-zA-Z]")

# ============================================================
# 域类型 pattern 注册表（顺序重要：长前缀优先匹配）
# ============================================================

DOMAIN_PATTERNS = [
    ("i_int", RE_I_INT),
    ("i_dec", RE_I_DEC),
    ("anc_var", RE_ANC_VAR),
    ("anc_fix", RE_ANC_FIX),
    ("anc_var_nolimit", RE_ANC_VAR_NOLIMIT),
    ("an_var", RE_AN_VAR),
    ("an_fix", RE_AN_FIX),
    ("an_var_nolimit", RE_AN_VAR_NOLIMIT),
    ("ac_var", RE_AC_VAR),
    ("ac_fix", RE_AC_FIX),
    ("ac_var_nolimit", RE_AC_VAR_NOLIMIT),
    ("nc_var", RE_NC_VAR),
    ("nc_fix", RE_NC_FIX),
    ("nc_var_nolimit", RE_NC_VAR_NOLIMIT),
    ("n_var", RE_N_VAR),
    ("n_fix", RE_N_FIX),
    ("n_var_nolimit", RE_N_VAR_NOLIMIT),
    ("a_var", RE_A_VAR),
    ("a_fix", RE_A_FIX),
    ("a_var_nolimit", RE_A_VAR_NOLIMIT),
    ("c_var", RE_C_VAR),
    ("c_fix", RE_C_FIX),
    ("c_var_nolimit", RE_C_VAR_NOLIMIT),
    ("date", RE_DATE),
    ("time", RE_TIME),
    ("datetime", RE_DATETIME),
    ("timestamp", RE_TIMESTAMP),
    ("time_p", RE_TIME_P),
    ("datetime_p", RE_DATETIME_P),
    ("timestamp_p", RE_TIMESTAMP_P),
]

# 域类型 -> 字符类别映射
DOMAIN_CHAR_CLASS = {
    "n_var": "n", "n_fix": "n", "n_var_nolimit": "n",
    "a_var": "a", "a_fix": "a", "a_var_nolimit": "a",
    "an_var": "an", "an_fix": "an", "an_var_nolimit": "an",
    "anc_var": "anc", "anc_fix": "anc", "anc_var_nolimit": "anc",
    "c_var": "c", "c_fix": "c", "c_var_nolimit": "c",
    "nc_var": "nc", "nc_fix": "nc", "nc_var_nolimit": "nc",
    "ac_var": "ac", "ac_fix": "ac", "ac_var_nolimit": "ac",
    "i_int": "i", "i_dec": "i",
    "date": "date", "time": "time",
    "datetime": "datetime", "timestamp": "timestamp",
    "time_p": "time", "datetime_p": "datetime", "timestamp_p": "timestamp",
}

# ============================================================
# 域类型白名单（按字段所属类型）
# ============================================================

DOMAIN_WHITELIST = {
    "数值类": {"i_int", "i_dec"},
    "日期时间类": {
        "date", "time", "datetime", "timestamp",
        "time_p", "datetime_p", "timestamp_p",
        "n_fix", "n_var",
        "an_fix", "an_var",
        "anc_fix", "anc_var",
    },
    "文本类": {
        "a_var", "a_fix", "a_var_nolimit",
        "n_var", "n_fix", "n_var_nolimit",
        "c_var", "c_fix", "c_var_nolimit",
        "an_var", "an_fix", "an_var_nolimit",
        "nc_var", "nc_fix", "nc_var_nolimit",
        "ac_var", "ac_fix", "ac_var_nolimit",
        "anc_var", "anc_fix", "anc_var_nolimit",
    },
    "编码类": {
        "a_var", "a_fix",
        "n_var", "n_fix",
        "an_var", "an_fix",
        "anc_var", "anc_fix",
    },
    "标志类": {"n_fix"},  # 特殊：仅 n!(1)，在节点中额外校验长度
    "代码枚举类": {
        "a_var", "a_fix",
        "n_var", "n_fix",
        "an_var", "an_fix",
    },
}

# 数据示例中的无效占位符（跳过检查）
INVALID_EXAMPLE_PLACEHOLDERS = {"无", "暂无", "无示例", "N/A", "n/a", "NA", "na"}
