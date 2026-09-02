# -*- coding: utf-8 -*-
"""域类型解析与校验 -- 质检/落标共用模块。

从 quality_check 下沉而来，消除两模块域校验逻辑漂移。

核心函数：
  - parse_domain_type(dt_str) -> (key, match)
  - check_data_example(domain_type, data_example) -> (ok, reason)

域类型规则参考 data/域类型说明.xlsx。
"""

import re

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
}

# 数据示例中的无效占位符（跳过检查）
INVALID_EXAMPLE_PLACEHOLDERS = {"无", "暂无", "无示例", "N/A", "n/a", "NA", "na"}

# 日期时间类允许的分隔符（strip 后校验纯数字位数）
_DATE_SEPARATORS = ("-", ":", "/", " ", "T")


# ============================================================
# 域类型解析
# ============================================================

def parse_domain_type(dt_str):
    """解析域类型字符串，返回 (pattern_key, match_obj) 或 (None, None)。"""
    dt = dt_str.strip()
    for key, regex in DOMAIN_PATTERNS:
        m = regex.match(dt)
        if m:
            return key, m
    return None, None


# ============================================================
# 字符类别判断
# ============================================================

def _is_chinese_char(ch):
    return "\u4e00" <= ch <= "\u9fff"


def _is_digit_char(ch):
    return ch in "0123456789"


def _is_letter_char(ch):
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def check_char_class(example, char_class):
    """检查数据示例的每个字符是否符合域类型的字符类别限制。

    Args:
        example: 数据示例字符串
        char_class: n/a/an/anc/c/nc/ac/i/date/time/datetime/timestamp

    Returns:
        (is_valid: bool, reason: str)
    """
    for ch in example:
        if char_class == "n":
            if not (_is_digit_char(ch) or ch in _DATE_SEPARATORS):
                return False, f"包含非法字符'{ch}'（数字字符类仅允许数字）"
        elif char_class == "a":
            if _is_digit_char(ch) or _is_chinese_char(ch):
                return False, f"包含不允许的字符'{ch}'（字母+特殊符号类不允许数字和汉字）"
        elif char_class == "an":
            if _is_chinese_char(ch):
                return False, f"包含汉字字符'{ch}'（数字+字母+特殊符号类不允许汉字）"
        elif char_class == "anc":
            pass  # 允许所有字符
        elif char_class == "c":
            if not _is_chinese_char(ch):
                return False, f"包含非汉字字符'{ch}'（纯汉字类仅允许汉字）"
        elif char_class == "nc":
            if not (_is_digit_char(ch) or _is_chinese_char(ch)):
                return False, f"包含不允许的字符'{ch}'（数字+汉字类仅允许数字和汉字）"
        elif char_class == "ac":
            if _is_digit_char(ch):
                return False, f"包含数字字符'{ch}'（字母+汉字类不允许数字）"
        elif char_class == "i":
            if not (_is_digit_char(ch) or ch in "+-."):
                return False, f"包含非数字字符'{ch}'（数值类仅允许数字、小数点和正负号）"
        elif char_class in ("date", "time", "datetime", "timestamp"):
            # date: 仅数字+分隔符
            # time/datetime/timestamp: 额外允许小数点（毫秒分隔符）
            allowed = set(_DATE_SEPARATORS)
            if char_class in ("time", "datetime", "timestamp"):
                allowed.add(".")
            if not (_is_digit_char(ch) or ch in allowed):
                return False, f"包含非法字符'{ch}'（日期时间类仅允许数字和分隔符-:/空格/T）"
    return True, ""


# ============================================================
# 长度/精度检查
# ============================================================

def check_length(example, domain_key, match):
    """检查数据示例的长度/精度是否符合域类型的限制。

    Returns:
        (is_valid: bool, reason: str)
    """
    is_nolimit = "_nolimit" in domain_key
    if is_nolimit:
        return True, ""

    is_fixed = "_fix" in domain_key

    # n/a/an/anc/c/nc/ac 变长或定长
    if domain_key in (
        "n_var", "n_fix", "a_var", "a_fix",
        "an_var", "an_fix", "anc_var", "anc_fix",
        "c_var", "c_fix", "nc_var", "nc_fix",
        "ac_var", "ac_fix",
    ):
        limit = int(match.group(1))
        if is_fixed:
            if len(example) != limit:
                return False, f"长度应为{limit}位，实际{len(example)}位"
        else:
            if len(example) > limit:
                return False, f"长度超过最大限制{limit}位，实际{len(example)}位"

    # i(x): 最多 x 位整数（符号 +/- 不计位数）
    elif domain_key == "i_int":
        x = int(match.group(1))
        if "." in example:
            return False, f"i({x})为整数类型，数据示例不应包含小数点"
        digits = example.lstrip("+-")
        if not digits:
            return False, "数据示例不是有效的数值"
        if len(digits) > x:
            return False, f"整数部分不得超过{x}位，实际{len(digits)}位"

    # i(x, y): 最多 x 位整数 + 最多 y 位小数（符号 +/- 不计位数）
    elif domain_key == "i_dec":
        x = int(match.group(1))
        y = int(match.group(2))
        if "." in example:
            parts = example.split(".", 1)
            int_part, dec_part = parts[0].lstrip("+-"), parts[1]
            if not int_part:
                return False, "数据示例不是有效的数值"
            if len(int_part) > x:
                return False, f"整数部分不得超过{x}位，实际{len(int_part)}位"
            if len(dec_part) > y:
                return False, f"小数部分不得超过{y}位，实际{len(dec_part)}位"
        else:
            digits = example.lstrip("+-")
            if not digits:
                return False, "数据示例不是有效的数值"
            if len(digits) > x:
                return False, f"整数部分不得超过{x}位，实际{len(digits)}位"

    # 日期时间类：先去除分隔符，再校验数字位数
    elif domain_key in ("date", "time", "datetime", "timestamp"):
        digits = example
        for sep in _DATE_SEPARATORS:
            digits = digits.replace(sep, "")

        if domain_key == "date":
            if len(digits) != 8:
                return False, f"DATE应为8位日期数字（YYYYMMDD），实际{len(digits)}位"

        elif domain_key == "time":
            # TIME: 6位HHMMSS，可带毫秒
            if "." in digits:
                parts = digits.split(".", 1)
                main_part, ms_part = parts[0], parts[1]
                if len(main_part) != 6:
                    return False, f"TIME应为6位时间数字（HHMMSS），实际{len(main_part)}位"
                if not ms_part.isdigit():
                    return False, f"毫秒部分应为纯数字，实际'{ms_part}'"
            else:
                if len(digits) != 6:
                    return False, f"TIME应为6位时间数字（HHMMSS），实际{len(digits)}位"

        elif domain_key in ("datetime", "timestamp"):
            # DATETIME/TIMESTAMP: 14位YYYYMMDDHHmmss，可带毫秒
            if "." in digits:
                parts = digits.split(".", 1)
                main_part, ms_part = parts[0], parts[1]
                if len(main_part) == 8:
                    return False, f"{domain_key.upper()}应为日期时间格式（YYYYMMDDHHmmss，14位），数据示例仅包含日期部分"
                if len(main_part) != 14:
                    return False, f"{domain_key.upper()}应为14位日期时间数字（YYYYMMDDHHmmss），实际{len(main_part)}位"
                if not ms_part.isdigit():
                    return False, f"毫秒部分应为纯数字，实际'{ms_part}'"
            else:
                if len(digits) == 8:
                    return False, f"{domain_key.upper()}应为日期时间格式（YYYYMMDDHHmmss，14位），数据示例仅包含日期部分"
                if len(digits) != 14:
                    return False, f"{domain_key.upper()}应为14位日期时间数字（YYYYMMDDHHmmss），实际{len(digits)}位"

    return True, ""


# ============================================================
# 组合校验
# ============================================================

def check_data_example(domain_type, data_example):
    """检查数据示例是否符合域类型的字符类别和长度精度限制。

    Args:
        domain_type: 域类型字符串（如 n..(10), i(15,2), DATE 等）
        data_example: 数据示例字符串

    Returns:
        (is_valid: bool, reason: str)
    """
    domain_key, match = parse_domain_type(domain_type)
    if domain_key is None:
        return True, ""  # 无法解析的域类型，跳过校验

    # 预处理：多个示例取第一个
    example = str(data_example).strip()
    for sep in [";", "；", ",", "，", "、"]:
        if sep in example:
            example = example.split(sep)[0].strip()
            break

    if not example or example in INVALID_EXAMPLE_PLACEHOLDERS:
        return True, ""

    # 字符类别检查
    char_class = DOMAIN_CHAR_CLASS.get(domain_key)
    if char_class:
        ok, reason = check_char_class(example, char_class)
        if not ok:
            return False, reason

    # 长度/精度检查
    ok, reason = check_length(example, domain_key, match)
    if not ok:
        return False, reason

    return True, ""
