"""埋雷引擎（01文档）。MVP：模板题方式——从YAML模式库加载带雷代码，生成MineManifest。"""

import random
import re
import uuid

import yaml

from ..config import PATTERNS_DIR

_patterns: dict[str, dict] = {}


def load_patterns() -> dict[str, dict]:
    global _patterns
    if not _patterns:
        for path in PATTERNS_DIR.rglob("*.yaml"):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            _patterns[data["id"]] = data
    return _patterns


def get_pattern(pattern_id: str) -> dict:
    return load_patterns()[pattern_id]


def pick_pattern(pattern_id: str | None = None) -> dict:
    patterns = load_patterns()
    if pattern_id:
        return patterns[pattern_id]
    return random.choice(list(patterns.values()))


def build_manifest(student_id: str, pattern: dict) -> dict:
    """生成雷清单（01文档 §5）——学生不可见，是导师与事件引擎的Ground Truth。"""
    return {
        "manifest_id": f"mm_{uuid.uuid4().hex[:12]}",
        "student_id": student_id,
        "mines": [
            {
                "mine_id": f"mine_{uuid.uuid4().hex[:8]}",
                "pattern_id": pattern["id"],
                "location": pattern["mine_location"],
                "trigger_input": pattern["trigger_input"],
                "root_cause": pattern["root_cause"],
                "expected_fix": pattern["expected_fix"],
                "fix_check": pattern["fix_check"],
                "hint_ladder": pattern["hint_ladder"],
                "internalize_questions": pattern["internalize_questions"],
                # V0.3变式题库预留接口：有则⑥内化后可出相似Bug检查迁移能力
                "variant_pool": pattern.get("variant_pool", []),
                "knowledge_points": pattern["knowledge_points"],
                "symptom": pattern["symptom"],
                "symptom_sample": pattern["symptom_sample"],
                "status": "planted",
            }
        ],
    }


def verify_fix(pattern_id: str, code: str) -> bool:
    """MVP判定：检查学生提交的代码是否包含预期修复（fix_check正则）。

    容忍括号/方括号内外的装饰性空格——range(len(arr) ) 与 range(len(arr)) 等价，
    避免把语义正确、只是多打了个空格的修复误判为失败。不动关键字间的空格
    （如 while n > 0、n -= 1），以免影响依赖空格的 fix_check。

    V0.3 换成沙箱真实运行触发测试（雷会响/不响）。
    """
    pattern = get_pattern(pattern_id)
    normalized = re.sub(r"\s+([)\]])", r"\1", code)       # 去掉 ) ] 前的空格
    normalized = re.sub(r"([(\[])\s+", r"\1", normalized)  # 去掉 ( [ 后的空格
    return re.search(pattern["fix_check"], normalized) is not None
