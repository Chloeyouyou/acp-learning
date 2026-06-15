"""规则型 Bug 分类器。

只负责把现有运行事实标准化为可派生的 bug_type / concept_tags。
不写数据库，不调用大模型，也不改变 ExecutionEvent schema。
"""

from __future__ import annotations

import re


_SIMPLE_RULES = {
    "KeyError": ("字典键不存在", ["字典", "键", "异常处理"]),
    "TypeError": ("类型错误", ["类型", "类型转换"]),
    "ValueError": ("值错误", ["值", "输入校验"]),
    "AttributeError": ("属性错误", ["对象", "属性", "空值检查"]),
    "NameError": ("变量未定义", ["变量", "作用域"]),
    "ZeroDivisionError": ("除以零", ["算术", "除法", "边界条件"]),
}

_NONE_RE = re.compile(
    r"\bnone(type)?\b|\bnull\b|空值|空对象|has no attribute",
    re.IGNORECASE,
)


def _contains(items: list[str], *needles: str) -> bool:
    text = " ".join(items).lower()
    return any(needle.lower() in text for needle in needles)


def classify_bug(
    error_family,
    stderr: str = "",
    pattern_id: str = "",
    knowledge_points=None,
) -> dict:
    """将运行错误映射为统一 Bug 分类。

    无法可靠识别时保留原 error_family，并降低 confidence，避免虚构分类。
    """
    family = str(error_family or "").strip()
    stderr = stderr or ""
    pattern_id = pattern_id or ""
    points = [str(item) for item in (knowledge_points or [])]
    evidence = " ".join([family, stderr, pattern_id, *points])

    if _NONE_RE.search(evidence):
        return {
            "bug_type": "空值未防护",
            "concept_tags": ["空值", "None", "防御式编程"],
            "confidence": "high" if family or stderr else "medium",
        }

    if family == "IndexError":
        if _contains(points, "字符串", "string") or re.search(
            r"string|string index|字符串", evidence, re.IGNORECASE
        ):
            return {
                "bug_type": "字符串下标越界",
                "concept_tags": ["字符串", "索引", "边界条件"],
                "confidence": "high",
            }
        if _contains(points, "数组", "列表", "array", "list"):
            return {
                "bug_type": "数组越界",
                "concept_tags": ["数组", "循环", "边界条件"],
                "confidence": "high",
            }
        return {
            "bug_type": "数组越界",
            "concept_tags": ["索引", "边界条件"],
            "confidence": "medium",
        }

    if family in _SIMPLE_RULES:
        bug_type, tags = _SIMPLE_RULES[family]
        return {
            "bug_type": bug_type,
            "concept_tags": list(tags),
            "confidence": "high",
        }

    if family:
        return {
            "bug_type": family,
            "concept_tags": points,
            "confidence": "low",
        }

    return {
        "bug_type": "未知错误",
        "concept_tags": points,
        "confidence": "low",
    }


if __name__ == "__main__":
    examples = [
        (
            {"error_family": "IndexError", "knowledge_points": ["数组"]},
            {
                "bug_type": "数组越界",
                "concept_tags": ["数组", "循环", "边界条件"],
                "confidence": "high",
            },
        ),
        (
            {"error_family": "IndexError", "knowledge_points": ["字符串"]},
            {
                "bug_type": "字符串下标越界",
                "concept_tags": ["字符串", "索引", "边界条件"],
                "confidence": "high",
            },
        ),
        (
            {
                "error_family": "AttributeError",
                "stderr": "'NoneType' object has no attribute 'name'",
            },
            {
                "bug_type": "空值未防护",
                "concept_tags": ["空值", "None", "防御式编程"],
                "confidence": "high",
            },
        ),
    ]

    for inputs, expected in examples:
        actual = classify_bug(**inputs)
        assert actual == expected, f"{inputs}: expected {expected}, got {actual}"
        print(f"{inputs} => {actual}")
