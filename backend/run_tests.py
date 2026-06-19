"""后端核心逻辑测试（零依赖，直接 `python run_tests.py`）。

锁住对错、防回归——重点覆盖踩过的隐蔽 bug：
- 选雷"补弱"方向（曾经符号反了，推强不推弱）
- 选雷"防套路"（不连续出同一题）
- 质检双关闸门（雷会响 / 雷能排 / fix_check）
- judge_fix 真判题、_error_family 解析、timeline 思维默认值聚合、sandbox。
用真沙箱跑代码，几秒内完成。
"""

import sys
import traceback

sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401  注册表到 Base.metadata
from app.db import Base
from app.models import ExecutionEvent, KnowledgeState, TutorSession
from app.services import event_engine, mine_engine, pattern_validator, profile, review, sandbox, timeline

_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
Base.metadata.create_all(_engine)
TestSession = sessionmaker(bind=_engine, autoflush=False)

_tests = []
def test(fn): _tests.append(fn); return fn


def _good_candidate() -> dict:
    """一道合规候选（buggy 真出 IndexError、fixed 跑出 2）。"""
    buggy = "def f(a):\n    return a[3]\nprint(f([1, 2]))\n"
    fixed = "def f(a):\n    return a[-1]\nprint(f([1, 2]))\n"
    return {
        "id": "BP-TEST-001", "name": "测试题", "category": "boundary", "language": "python",
        "knowledge_points": ["数组"], "capability_dims": ["Boundary_Awareness"],
        "difficulty": "L1", "symptom": "RE", "symptom_sample": "IndexError: list index out of range",
        "buggy_code": buggy, "fixed_code": fixed,
        "mine_location": {"file": "main.py", "line": 2}, "trigger_input": "[1, 2]",
        "root_cause": "下标 3 越界", "cognitive_root": "以为列表一定有第 4 个元素",
        "thinking_pattern": "index_confusion", "expected_fix": "a[-1]", "fix_check": r"a\[-1\]",
        "expected_output": "2",
        "internalize_questions": ["为什么越界？", "合法下标范围是？"],
        "hint_ladder": {f"L{i}": f"提示{i}" for i in range(6)},
    }


# ---- 选雷：补弱（曾经符号反了，推强不推弱）----
@test
def picker_选薄弱而非最强():
    orig = profile.knowledge_mastery
    profile.knowledge_mastery = lambda db, sid: [
        {"kp": "强项", "mastery": "熟练", "weak": False},
        {"kp": "弱项", "mastery": "生疏", "weak": True},
    ]
    try:
        db = TestSession()
        pats = [{"id": "STRONG", "knowledge_points": ["强项"], "difficulty": "L1"},
                {"id": "WEAK", "knowledge_points": ["弱项"], "difficulty": "L1"}]
        got = profile.get_weakest_pattern_id(db, "s1", pats)
        assert got == "WEAK", f"应推薄弱题 WEAK，实际 {got}（符号又反了？）"
        db.close()
    finally:
        profile.knowledge_mastery = orig


# ---- 选雷：防套路（不连续出同一题）----
@test
def picker_不连续出同一题():
    orig = profile.knowledge_mastery
    profile.knowledge_mastery = lambda db, sid: [
        {"kp": "弱项", "mastery": "生疏", "weak": True},
        {"kp": "次弱", "mastery": "在学", "weak": False},
    ]
    try:
        db = TestSession()
        db.add(TutorSession(id="sess_x", student_id="s2", pattern_id="WEAK", manifest={}, history=[]))
        db.commit()
        pats = [{"id": "WEAK", "knowledge_points": ["弱项"], "difficulty": "L1"},
                {"id": "SECOND", "knowledge_points": ["次弱"], "difficulty": "L1"}]
        got = profile.get_weakest_pattern_id(db, "s2", pats)
        assert got != "WEAK", "上次刚做 WEAK，不该又出 WEAK"
        db.close()
    finally:
        profile.knowledge_mastery = orig


# ---- 质检双关 ----
@test
def 质检_合规候选全过():
    problems = pattern_validator.validate_candidate(_good_candidate())
    assert not problems, f"合规候选不该有问题：{problems}"

@test
def 质检_雷不响要拦():
    c = _good_candidate()
    c["buggy_code"] = "x = 1\nprint(2)\n"  # 两行(line:2 仍合法)、不报错，但声明 RE
    problems = pattern_validator.validate_candidate(c)
    assert any("雷没响" in p for p in problems), f"雷不响应被拦：{problems}"

@test
def 质检_fixcheck匹配带雷码要拦():
    c = _good_candidate()
    c["fix_check"] = r"def f"             # 也匹配 buggy_code
    problems = pattern_validator.validate_candidate(c)
    assert any("buggy_code" in p for p in problems), f"应拦原样可过：{problems}"

@test
def 质检_跑题要拦():
    # 订单要 arithmetic/WA，候选交了 boundary/RE → 对单不通过
    c = _good_candidate()  # category=boundary, symptom=RE
    task = {"category": "arithmetic", "thinking_pattern": "control_semantics", "error_target": "WA"}
    problems = pattern_validator.validate_candidate(c, task)
    assert any("跑题" in p for p in problems), f"对不上订单应被拦：{problems}"
    # 对得上订单时不因对单报错
    task_ok = {"category": "boundary", "thinking_pattern": "index_confusion", "error_target": "RE"}
    assert not pattern_validator.validate_candidate(c, task_ok), "对得上订单不该被拦"

@test
def 质检_缺字段要拦():
    c = _good_candidate(); del c["cognitive_root"]
    problems = pattern_validator.validate_candidate(c)
    assert any("cognitive_root" in p for p in problems), problems


# ---- judge_fix 真判题 ----
@test
def judge_带雷码不通过_修对通过():
    bad = mine_engine.judge_fix("BP-BOUNDARY-001", mine_engine.get_pattern("BP-BOUNDARY-001")["buggy_code"])
    assert not bad["passed"], "带雷代码不该通过"
    fixed = mine_engine.get_pattern("BP-BOUNDARY-001")["buggy_code"].replace("range(len(arr) + 1)", "range(len(arr))")
    good = mine_engine.judge_fix("BP-BOUNDARY-001", fixed)
    assert good["passed"], f"正确修复应通过：{good}"


# ---- 事件：错误族解析 ----
@test
def error_family_解析():
    assert event_engine._error_family("RE", "Traceback...\nIndexError: x") == "IndexError"
    assert event_engine._error_family("HANG", "") == "Timeout"
    assert event_engine._error_family("WA", "") == "WrongAnswer"
    assert event_engine._error_family("OK", "") is None


# ---- timeline：观察卡解析 + 思维默认值聚合 ----
@test
def timeline_观察卡解析():
    obs, guess = timeline._parse_observation(
        [{"role": "user", "content": "【观察记录】\n我观察到：第一行少了\n我的猜测：循环错"}])
    assert obs == "第一行少了" and guess == "循环错", (obs, guess)

@test
def timeline_跨题思维默认值聚合():
    eps = [{"pattern_id": "BP-NULL-002", "pattern_name": "方法返回None未检查"},
           {"pattern_id": "BP-NULL-003", "pattern_name": "字典取值未判空"}]  # 同 assume_valid 簇
    res = timeline.aggregate_thinking_patterns(eps)
    assert res.get("enough") and any(it["id"] == "assume_valid" for it in res["items"]), res


# ---- 题库统计（曾经只吃 list、传 dict 报错）----
@test
def collect_stats_兼容dict():
    pats = mine_engine.load_patterns()  # dict[id->题]
    s = pattern_validator.collect_stats(pats)
    assert s["total"] == len(pats) and sum(s["category"].values()) == s["total"], s


# ---- 复习队列（间隔重复）----
import uuid as _uuid
from datetime import date as _date, datetime as _dt, timedelta as _td

_REVIEW_PID = "BP-BOUNDARY-001"  # 用真实题，name/category 能填上

def _seed_solved(db, student_id, pid, *, state, solved_days_ago: list[int]):
    """造一道「已解决/已内化」题 + 若干天前的 submit/OK 执行事实。"""
    db.add(KnowledgeState(student_id=student_id, pattern_id=pid,
                          knowledge_points=["数组"], state=state))
    base = _dt.now()
    for d in solved_days_ago:
        db.add(ExecutionEvent(
            id=f"ex_{_uuid.uuid4().hex[:12]}", version="v1", student_id=student_id,
            session_id=f"sess_{_uuid.uuid4().hex[:8]}", pattern_id=pid,
            source="submit", kind="OK", knowledge_points=["数组"], meta={},
            timestamp=(base - _td(days=d)).isoformat()))
    db.commit()

@test
def review_旧题到期进队列():
    db = TestSession()
    sid = "rev_due"
    _seed_solved(db, sid, _REVIEW_PID, state="已解决", solved_days_ago=[10])  # round1 间隔2，10>=2
    due = review.due_queue(db, sid)
    assert any(it["pattern_id"] == _REVIEW_PID for it in due), f"10天前解决的应到期：{due}"
    it = next(it for it in due if it["pattern_id"] == _REVIEW_PID)
    assert it["due"] and it["name"] and it["category"], it
    db.close()

@test
def review_刚解决不到期():
    db = TestSession()
    sid = "rev_fresh"
    _seed_solved(db, sid, _REVIEW_PID, state="已解决", solved_days_ago=[0])  # 今天解决，0<2
    due = review.due_queue(db, sid)
    assert not any(it["pattern_id"] == _REVIEW_PID for it in due), f"刚解决不该到期：{due}"
    db.close()

@test
def review_间隔随轮次升档():
    # 已解决 round1=2天、round2=4天；已内化整体更长
    assert review._interval_for("已解决", 1) == 2
    assert review._interval_for("已解决", 2) == 4
    assert review._interval_for("已内化", 1) > review._interval_for("已解决", 1)
    # 多次解决（不同天）→ 轮次变高、间隔变长 → 同样 days_since 可能不到期
    db = TestSession()
    sid = "rev_round"
    _seed_solved(db, sid, _REVIEW_PID, state="已内化", solved_days_ago=[40, 20, 5])  # round3
    due = review.due_queue(db, sid)
    it = [x for x in due if x["pattern_id"] == _REVIEW_PID]
    # 最近一次 5 天前，已内化 round3 间隔=15，5<15 → 不到期
    assert not it, f"round3 已内化 5天前不该到期：{due}"
    db.close()

@test
def review_未解决题不进队列():
    db = TestSession()
    sid = "rev_open"
    db.add(KnowledgeState(student_id=sid, pattern_id=_REVIEW_PID,
                          knowledge_points=["数组"], state="已接触"))
    db.commit()
    assert not review.due_queue(db, sid), "未解决（已接触）不该进复习队列"
    db.close()


# ---- sandbox ----
@test
def sandbox_基本():
    assert sandbox.run_code("print(1+1)").stdout.strip() == "2"
    assert sandbox.run_code("raise ValueError()").has_error
    assert sandbox.normalize_output("  6  ") == "6"


def main():
    passed = failed = 0
    for fn in _tests:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {fn.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} 过 / {failed} 败 / 共 {len(_tests)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
