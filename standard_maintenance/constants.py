# -*- coding: utf-8 -*-
"""标准维护 -- 常量定义。

字典新增逻辑的输入列映射与"变更标准"输出列定义。
"""

# ============================================================
# 输入列名（与质检输出格式一致，精确匹配）
# ============================================================

INPUT_COLUMNS = {
    "field_name": ["中文字段名(必填)"],
    "field_type": ["字段所属类型(必填)"],
    "is_enum": ["是否枚举(必填)"],
    "enum_values": ["枚举值(选填)"],
    "business_meaning": ["业务定义(必填)"],
}

# ============================================================
# 输出新增列名（顺序即输出列顺序）
# ============================================================

COL_STD_ID = "标准编号"
COL_FIELD_NAME = "中文字段名"
COL_FIELD_TYPE = "字段所属类型"
COL_IS_ENUM = "是否枚举"
COL_ENUM_VALUES = "枚举值"
COL_DEFINITION = "业务定义"

RESULT_COLUMNS = [
    COL_STD_ID,
    COL_FIELD_NAME,
    COL_FIELD_TYPE,
    COL_IS_ENUM,
    COL_ENUM_VALUES,
    COL_DEFINITION,
]

# 输出第1行合并表头组名
GROUP_CHANGE_STANDARD = "变更标准"
