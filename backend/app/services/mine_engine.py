"""埋雷引擎（01文档）。MVP：模板题方式——从YAML模式库加载带雷代码，生成MineManifest。"""

import random
import re
import uuid

import yaml

from ..config import PATTERNS_DIR
from . import sandbox

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



def pick_pattern_for_student(
    student_id: str | None = None,
    pattern_id: str | None = None,
    db: "Session | None" = None,
) -> dict:
    """画像驱动选雷（替代 random.choice）。支持三种模式：

    1. 指定 pattern_id -> 直接返回（向后兼容）
    2. 有 db + student_id -> 画像驱动选最薄弱知识点对应题目
    3. 无 db/student_id -> 回退到 random.choice
    """
    patterns = load_patterns()

    # 模式1：指定题目
    if pattern_id:
        return patterns[pattern_id]

    # 模式2：画像驱动选雷
    if db is not None and student_id is not None:
        from . import profile  # 延迟导入避免循环依赖

        best_id = profile.get_weakest_pattern_id(db, student_id, list(patterns.values()))
        if best_id and best_id in patterns:
            return patterns[best_id]

    # 模式3：回退随机
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


def judge_fix(pattern_id: str, code: str) -> dict:
    """路线A判题：真跑学生代码，按运行结果判对错（替代正则文字匹配）。

    返回 {passed, kind, stdout, stderr, expected}：
    - 跑通且无报错且（有 expected_output 时）输出匹配 → passed=True, kind="ok"
    - 超时 → kind="HANG"；报错 → kind="RE"；跑通但输出不符 → kind="WA"
    expected_output 可选：确定型题目精确比对；优雅处理型题目（如空输入）省略，只要求不报错。
    """
    pattern = get_pattern(pattern_id)
    r = sandbox.run_code(code)
    expected = pattern.get("expected_output")
    if r.timed_out:
        kind, passed = "HANG", False
    elif r.has_error:
        kind, passed = "RE", False
    elif expected is not None and sandbox.normalize_output(r.stdout) != sandbox.normalize_output(expected):
        kind, passed = "WA", False
    else:
        kind, passed = "ok", True
    return {"passed": passed, "kind": kind, "stdout": r.stdout,
            "stderr": r.stderr, "expected": expected}


def verify_fix(pattern_id: str, code: str) -> bool:
    """布尔判定（向后兼容）：真跑学生代码判对错。详见 judge_fix。"""
    return judge_fix(pattern_id, code)["passed"]
