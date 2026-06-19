"""自动出题工厂（调度器）。Planner 任务 → LLM 生成 → 沙箱双关质检 → 重试 → 落 _pending。

factory 只做编排，不含"智能"：
  task → generate_candidate(LLM) → derive expected_output(跑 fixed) → validate_candidate(闸门) → 过则写 _pending
质检不过即丢弃、自动重试。生成是作者侧工具，绝不进学生端。
"""

import json
import uuid

import yaml

from ..config import PATTERNS_DIR, TUTOR_MODEL
from . import mine_engine, pattern_validator, sandbox, tutor

PENDING_DIR = PATTERNS_DIR / "_pending"

# 生成期专用字段（不入库）：质检用完即从落盘的 YAML 里剥掉
_GEN_ONLY = ("fixed_code", "tests")

SYSTEM = """你是给【零基础初学者】出 Python 调试练习题的命题专家。
你要按给定目标，造一道"带雷"的题：一段**自包含、可直接运行**的 Python 脚本（像范例那样，最后用一行写死的调用并 print 结果），里面藏一个真实 Bug。
风格、难度、教学口吻必须和范例完全一致。严格输出 JSON，不要任何解释。"""

# 字段契约（与手写 15 题同规格）+ 生成期附加 fixed_code
SCHEMA_HINT = """输出 JSON，含且仅含这些键：
id 可留空（系统会分配）。
name(中文题名), category(boundary|loop|null|arithmetic), language("python"),
knowledge_points(中文数组), capability_dims(从 Boundary_Awareness/Independent_Debug/Root_Cause_Reasoning/Hypothesis_Testing/Log_Reading 选),
difficulty(L1-L5), symptom(RE|WA|HANG), symptom_sample(真实报错/现象样例,多行字符串),
buggy_code(自包含可运行、含写死调用与 print 的带雷脚本),
fixed_code(把雷修好后的【完整正确脚本】,只改最小处),
mine_location({file:"main.py", line:雷所在行号}), trigger_input(触发输入的文字描述),
root_cause(一句话讲清代码机制层面为什么错),
cognitive_root(一句话点破【认知漏洞】——学习者脑子里哪个默认假设错了,不是代码层),
thinking_pattern(assume_valid|index_confusion|loop_progress|crash_site|control_semantics|shared_state 选最贴的),
expected_fix(修复的关键代码片段), fix_check(一个正则:能匹配 fixed_code、不匹配 buggy_code),
expected_output(fixed_code 跑出的正确输出),
internalize_questions(≥2 个引导学生复述成因/迁移的问题),
hint_ladder({L0..L5} 六档,从"自己多试"到"讲思路但不给改法",【只引导绝不给出修改后的代码】)。

铁律：
- buggy_code 必须真能跑出声明的 symptom（RE 真抛异常 / HANG 真死循环 / WA 真算错）。
- hint_ladder、internalize_questions 绝不剧透 bug、绝不直接给改法。
- 【L5 红线·最易犯】L5 是"讲思路的上限"，只点破认知方向（如"想想这个运算到底做了什么"），
  **绝不能出现具体改法**：不准说"应该用 X/改成 X/换成 Y 函数"、不准点名正确的运算符或函数（如"用 / "、"用 round"）。
  写完 L5 自检：如果学生照着 L5 一字不改就能改对，就是泄题，重写。
- cognitive_root 必须是"认知/思维默认值"层面的话，不是复述代码。
- symptom_sample 简短一句（一个触发输入 + 错误现象），不要长篇罗列多组输入。"""


def _examples(category: str, k: int = 2) -> str:
    """取 k 道现有题的 YAML 原文做 few-shot（优先同类）。"""
    pats = list(mine_engine.load_patterns().values())
    same = [p for p in pats if p.get("category") == category]
    others = [p for p in pats if p.get("category") != category]
    chosen = (same[:1] + others[:1]) if same else pats[:k]
    chosen = chosen[:k]
    return "\n\n".join(yaml.safe_dump(p, allow_unicode=True, sort_keys=False) for p in chosen)


def _new_id() -> str:
    existing = set(mine_engine.load_patterns())
    while True:
        cand = f"BP-GEN-{uuid.uuid4().hex[:6].upper()}"
        if cand not in existing:
            return cand


def generate_candidate(task: dict) -> dict | None:
    """调 LLM 产一道候选题（含 fixed_code）。失败返回 None。"""
    user = (f"出题目标：\n"
            f"- category: {task['category']}\n- difficulty: {task['difficulty']}\n"
            f"- thinking_pattern: {task['thinking_pattern']}\n- 症状(symptom/error_target): {task['error_target']}\n"
            f"- knowledge_points 倾向: {task.get('knowledge_points') or '自定（贴合 category）'}\n"
            f"- 约束: {task.get('constraints')}\n"
            f"- 场景种子: {task.get('seed') or '自定一个生活化小场景'}\n\n"
            f"{SCHEMA_HINT}\n\n参考范例（YAML，照这个风格/难度/口吻，但题目内容要新）：\n{_examples(task['category'])}")
    try:
        resp = tutor.client.chat.completions.create(
            model=TUTOR_MODEL,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            temperature=0.7, max_tokens=2600,
            response_format={"type": "json_object"},
        )
        cand = json.loads(resp.choices[0].message.content or "{}")
    except (json.JSONDecodeError, Exception):
        return None
    if not isinstance(cand, dict) or not cand.get("buggy_code") or not cand.get("fixed_code"):
        return None
    cand["id"] = _new_id()
    cand.setdefault("language", "python")
    # expected_output 不信 LLM，跑 fixed_code 现得（保证自洽）
    r = sandbox.run_code(cand["fixed_code"])
    if not r.timed_out and not r.has_error:
        cand["expected_output"] = sandbox.normalize_output(r.stdout)
    return cand


def write_pending(cand: dict) -> str:
    """过闸候选写入 patterns/_pending/<id>.yaml（剥掉生成期专用字段）。"""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    out = {k: v for k, v in cand.items() if k not in _GEN_ONLY}
    path = PENDING_DIR / f"{cand['id']}.yaml"
    path.write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return str(path)


def generate_batch(tasks: list, retries: int = 3) -> dict:
    """对每个 task 生成→质检→重试。返回 {accepted:[...], failed:[...]}。"""
    accepted, failed = [], []
    for i, task in enumerate(tasks, 1):
        t = task.to_dict() if hasattr(task, "to_dict") else task
        ok = False
        for attempt in range(1, retries + 1):
            print(f"[任务 {i}/{len(tasks)}] 第 {attempt} 次生成 ({t['category']}/{t['difficulty']}/{t['thinking_pattern']}/{t['error_target']})…")
            cand = generate_candidate(t)
            if cand is None:
                print("   ✗ 生成/解析失败，重试")
                continue
            problems = pattern_validator.validate_candidate(cand, t)
            if not problems:
                path = write_pending(cand)
                print(f"   ✓ 通过双关质检 → {path}")
                accepted.append(cand["id"])
                ok = True
                break
            print("   ✗ 质检未过：" + "；".join(problems))
        if not ok:
            failed.append(t)
    return {"accepted": accepted, "failed": failed}
