"""检索前预处理：基于近义词表对字段名做后缀级同义扩展。

近义词表从 standard_mapping/synonyms.json 读取（可随时修改，无需改代码）；
JSON 缺失或格式错误时回退为空表（即不做扩展）。

当前规则（全局后缀规则）：suffix_synonym_groups 为同义词组列表，每组含 2 个
及以上同义后缀。字段名以组内【任意一个】后缀结尾时，用组内【其他每个】后缀
各生成一个变体名去召回；双向生效。
例：客户编号 -> [客户编号, 客户号]；客户号 -> [客户号, 客户编号]。
副作用（已接受）：手机号 也会生成 手机编号，仅影响召回，不影响 LLM 判断。
"""

import json
import os

# 近义词表配置文件路径（与模块同目录）
_SYNONYMS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "synonyms.json")


def _load_suffix_synonym_groups() -> list[list[str]]:
    """从 JSON 配置文件加载同义词组；文件缺失/格式错误时回退空表。"""
    try:
        with open(_SYNONYMS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        groups = []
        for group in data.get("suffix_synonym_groups", []):
            cleaned = [str(s).strip() for s in group if str(s).strip()]
            if len(cleaned) >= 2:
                groups.append(cleaned)
        return groups
    except (OSError, ValueError) as e:
        print(f"  [WARNING] 近义词表 {_SYNONYMS_FILE} 读取失败，本次不做扩展: {e}")
        return []


SUFFIX_SYNONYM_GROUPS: list[list[str]] = _load_suffix_synonym_groups()


def _build_suffix_group_map(groups: list[list[str]]) -> dict[str, list[str]]:
    """把同义词组展开为 后缀 -> 所属组 的映射，便于按最长后缀定位。"""
    suffix_group = {}
    for group in groups:
        for suffix in group:
            suffix_group[suffix] = group
    return suffix_group


def preprocess_field_name(field_name: str) -> list[str]:
    """对待落标字段名做近义词扩展，返回查询名列表（原始名在首位）。

    关键实现点：
    - 命中多个后缀时取【最长命中后缀】替换：因"编号"本身以"号"结尾，
      若不取最长，字段名"客户编号"会同时满足 endswith("编号") 与
      endswith("号")，生成错误变体"客户编编号"。
    - 用最长命中后缀所在组内的【其他每个】同义后缀各生成一个变体。
    - 无后缀命中时返回 [field_name]（保持原有单名检索行为）。
    """
    if not field_name:
        return [field_name]

    suffix_group = _build_suffix_group_map(SUFFIX_SYNONYM_GROUPS)

    matched = None
    for suffix in suffix_group:
        if field_name.endswith(suffix):
            if matched is None or len(suffix) > len(matched):
                matched = suffix

    if matched is None:
        return [field_name]

    results = [field_name]
    stem = field_name[: -len(matched)]
    for member in suffix_group[matched]:
        if member == matched:
            continue
        results.append(stem + member)
    return results
