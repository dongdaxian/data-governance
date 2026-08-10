# -*- coding: utf-8 -*-
"""数据质量检查 -- 常量定义。

域类型正则规则、字符类别映射、数据示例校验等已下沉到 common/domain_rules.py。
本文件仅保留质检专用常量（字段类型、列名、域类型白名单、输出列名）。
"""

# ============================================================
# 字段类型
# ============================================================

# 合法的字段所属类型
VALID_FIELD_TYPES = ["数值类", "编码类", "代码枚举类", "日期时间类", "标志类", "文本类"]

# 非代码枚举类类型
NON_ENUM_TYPES = ["数值类", "编码类", "日期时间类", "标志类", "文本类"]

# ============================================================
# 输入列名
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
