"""数据质量检查 -- Excel 列名常量。"""

# 输入列名（支持模糊匹配）
INPUT_COLUMNS = {
    "field_name": ["字段中文名", "字段名称", "中文名", "字段名"],
    "field_type": ["字段所属类型", "字段类型", "所属类型", "类型"],
    "business_meaning": ["业务含义", "含义", "业务说明", "说明"],
    "enum_values": ["枚举值", "枚举", "码值", "代码值"],
}

# 合法的字段所属类型
VALID_FIELD_TYPES = ["数值类", "编码类", "代码枚举类", "日期时间类", "标志类", "文本类"]

# 输出新增列名
COL_NORMALIZED_ENUM = "规范化后的枚举值"
COL_CHECK_RESULT = "检查结果"
COL_FAIL_REASON = "不通过原因"
