"""题目质检（E 自动出题工厂的闸门 + 题库入库校验，单一来源）。

两种用法：
- validate_candidate(cand)：生成期闸门。cand 含 fixed_code（正确版）→ 跑双关：
  雷会响（buggy 真出声明症状）+ 雷能排（fixed 跑通且输出== expected_output）。
- validate_library_pattern(p)：题库 YAML 校验（无 fixed_code）→ 只查结构 + 雷会响 + fix_check。

只判"单题对错"。题库分布统计 collect_stats 也放这里供 Planner 用（但不属于单题校验）。
铁律：纯读、真跑用沙箱；不改 schema/判题/事件流。
"""

import re
from collections import Counter

from . import sandbox
from ..registry import CAPABILITY_REGISTRY

# expected_output 为可选：优雅处理型题（修复=不再崩，无单一标准输出）可不带；judge_fix 有则比对、无则只验不报错
REQUIRED = ["id", "name", "category", "language", "knowledge_points", "capability_dims",
            "difficulty", "symptom", "symptom_sample", "buggy_code", "mine_location",
            "trigger_input", "root_cause", "cognitive_root", "thinking_pattern",
            "expected_fix", "fix_check", "internalize_questions", "hint_ladder"]

CATEGORIES = {"boundary", "loop", "null", "arithmetic"}
THINKING_PATTERNS = {"assume_valid", "index_confusion", "loop_progress",
                     "crash_site", "control_semantics", "shared_state"}
SYMPTOMS = {"RE", "WA", "HANG"}
DIFFICULTIES = {"L1", "L2", "L3", "L4", "L5"}


def _run_symptom(code: str) -> str:
    """跑一段自包含脚本，归一成 RE / HANG / OK。"""
    r = sandbox.run_code(code)
    if r.timed_out:
        return "HANG"
    return "RE" if r.has_error else "OK"


def check_structure(p: dict) -> list[str]:
    problems = []
    for field in REQUIRED:
        if not p.get(field) and p.get(field) != 0:
            problems.append(f"缺少/空字段 {field}")
    if set(p.get("hint_ladder", {}) or {}) != {"L0", "L1", "L2", "L3", "L4", "L5"}:
        problems.append("hint_ladder 必须恰好含 L0-L5")
    if len(p.get("internalize_questions", []) or []) < 2:
        problems.append("internalize_questions 至少 2 个")
    if p.get("category") not in CATEGORIES:
        problems.append(f"category 不在词表：{p.get('category')}")
    if p.get("thinking_pattern") not in THINKING_PATTERNS:
        problems.append(f"thinking_pattern 不在词表：{p.get('thinking_pattern')}")
    if p.get("symptom") not in SYMPTOMS:
        problems.append(f"symptom 必须是 RE/WA/HANG：{p.get('symptom')}")
    if p.get("difficulty") not in DIFFICULTIES:
        problems.append(f"difficulty 必须是 L1-L5：{p.get('difficulty')}")
    for cap in p.get("capability_dims", []) or []:
        if cap not in CAPABILITY_REGISTRY:
            problems.append(f"capability_dims 含未注册能力：{cap}")
    loc = p.get("mine_location") or {}
    if not isinstance(loc, dict) or "line" not in loc:
        problems.append("mine_location 需含 line")
    else:
        n_lines = len((p.get("buggy_code") or "").splitlines())
        if not (1 <= int(loc.get("line", 0)) <= max(n_lines, 1)):
            problems.append(f"mine_location.line 超出代码行数（{loc.get('line')} / {n_lines}）")
    return problems


def check_fix_check(p: dict, fixed_code: str | None = None) -> list[str]:
    problems = []
    fc = p.get("fix_check")
    if not fc:
        return ["缺少 fix_check"]
    try:
        if re.search(fc, p.get("buggy_code", "")):
            problems.append("fix_check 匹配了 buggy_code——原样提交即可通过！")
        if fixed_code is not None and not re.search(fc, fixed_code):
            problems.append("fix_check 不匹配 fixed_code——无法判定正确修复")
    except re.error as e:
        problems.append(f"fix_check 不是合法正则：{e}")
    return problems


def check_symptom(p: dict) -> list[str]:
    """雷会响：buggy_code 真出声明的症状。"""
    declared = p.get("symptom")
    actual = _run_symptom(p.get("buggy_code", ""))
    if declared == "RE" and actual != "RE":
        return [f"症状声明 RE 但实际 {actual}（雷没响）"]
    if declared == "HANG" and actual != "HANG":
        return [f"症状声明 HANG 但实际 {actual}（雷没响）"]
    if declared == "WA":
        if actual != "OK":
            return [f"症状声明 WA 但运行是 {actual}（WA 类应正常退出）"]
        if not p.get("expected_output"):
            return ["症状声明 WA 但缺 expected_output（无法定义『算错』）"]
        out = sandbox.normalize_output(sandbox.run_code(p["buggy_code"]).stdout)
        if out == sandbox.normalize_output(p["expected_output"]):
            return ["症状声明 WA 但 buggy 输出与 expected_output 相同（其实没错）"]
    return []


def check_fix_resolves(p: dict, fixed_code: str) -> list[str]:
    """雷能排：fixed_code 跑通且输出 == expected_output。"""
    if not fixed_code:
        return ["缺少 fixed_code（生成期质检必需）"]
    r = sandbox.run_code(fixed_code)
    if r.timed_out:
        return ["fixed_code 超时（修复后仍卡住）"]
    if r.has_error:
        last = (r.stderr or "").strip().splitlines()[-1:] or ["?"]
        return [f"fixed_code 仍报错（雷没排掉）：{last[0]}"]
    # 有 expected_output 才比对；优雅处理型（无期望输出）只要求修复后跑通不报错
    if p.get("expected_output") and \
            sandbox.normalize_output(r.stdout) != sandbox.normalize_output(p["expected_output"]):
        return ["fixed_code 输出与 expected_output 不一致"]
    return []


def check_task_match(cand: dict, task: dict) -> list[str]:
    """对单：生成结果须符合订单的 category / thinking_pattern / 症状。

    否则就是「让补 arithmetic 它却交了一道 null 题」——缺口没真补上。
    """
    problems = []
    if task.get("category") and cand.get("category") != task["category"]:
        problems.append(f"跑题：category 要 {task['category']}，实为 {cand.get('category')}")
    if task.get("thinking_pattern") and cand.get("thinking_pattern") != task["thinking_pattern"]:
        problems.append(f"跑题：thinking_pattern 要 {task['thinking_pattern']}，实为 {cand.get('thinking_pattern')}")
    want_sym = task.get("error_target") or task.get("symptom")
    if want_sym and cand.get("symptom") != want_sym:
        problems.append(f"跑题：症状要 {want_sym}，实为 {cand.get('symptom')}")
    return problems


def validate_candidate(cand: dict, task: dict | None = None) -> list[str]:
    """生成期闸门：[对单] + 结构 + fix_check + 雷会响 + 雷能排。cand 需含 fixed_code。"""
    fixed = cand.get("fixed_code")
    problems = []
    if task:
        problems += check_task_match(cand, task)
    problems += check_structure(cand)
    problems += check_fix_check(cand, fixed)
    # 结构都不全就别跑代码了，避免噪声
    if not problems or all("fix_check" in x for x in problems):
        problems += check_symptom(cand)
        problems += check_fix_resolves(cand, fixed)
    return problems


def validate_library_pattern(p: dict) -> list[str]:
    """题库 YAML 校验（无 fixed_code）：结构 + fix_check 不匹配带雷码 + 雷会响。"""
    problems = []
    problems += check_structure(p)
    problems += check_fix_check(p)
    problems += check_symptom(p)
    return problems


def collect_stats(patterns) -> dict:
    """题库分布统计（给 Planner 填缺口/防偏；不属于单题校验）。

    兼容 list[dict] 和 mine_engine.load_patterns() 的 dict[id->题]。
    """
    if isinstance(patterns, dict):
        patterns = list(patterns.values())
    return {
        "total": len(patterns),
        "category": dict(Counter(p.get("category") for p in patterns)),
        "symptom": dict(Counter(p.get("symptom") for p in patterns)),
        "thinking_pattern": dict(Counter(p.get("thinking_pattern") for p in patterns)),
        "difficulty": dict(Counter(p.get("difficulty") for p in patterns)),
    }
