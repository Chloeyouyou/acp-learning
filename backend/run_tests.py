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


# ---- 知返反幻觉：运行结果注入（截断 + 只留最新一条）----
from app.services import tutor

@test
def run_note_截断长输出():
    note = tutor.run_result_note("OK", stdout="x" * 5000)
    assert note.startswith(tutor.RUN_RESULT_PREFIX), note
    assert "截断" in note and len(note) < 800, f"长输出必须截断：{len(note)}"

@test
def run_note_报错只留尾部():
    long_tb = "Traceback...\n" + "f\n" * 2000 + "ZeroDivisionError: division by zero"
    note = tutor.run_result_note("RE", stderr=long_tb)
    assert tutor.RUN_RESULT_PREFIX in note and "ZeroDivisionError" in note
    assert len(note) < 800, "报错应只留尾部"

@test
def run_note_超时():
    note = tutor.run_result_note("HANG")
    assert "超时" in note or "死循环" in note

@test
def inject_只保留最新一条运行结果():
    h = [{"role": "user", "content": "我观察到了"},
         {"role": "assistant", "content": "嗯"}]
    h = tutor.inject_run_note(h, tutor.run_result_note("OK", stdout="第一次"))
    h = tutor.inject_run_note(h, tutor.run_result_note("RE", stderr="第二次错误"))
    notes = [m for m in h if (m.get("content") or "").startswith(tutor.RUN_RESULT_PREFIX)]
    assert len(notes) == 1, f"只该留最新一条运行结果，实际 {len(notes)}"
    assert "第二次错误" in notes[0]["content"], "留下的应是最新那条"
    # 非运行结果的历史不能被误删
    assert any(m["content"] == "我观察到了" for m in h), "普通历史不该被剔除"


# ---- 接着做（未完成关卡续做）：cleanup / active-sessions / abandon（设计 08）----
from app.main import _cleanup_abandoned, abandon_session, get_active_sessions

_AS_PID = "BP-BOUNDARY-001"  # 用真实题，name 能填上

def _mk_active(db, sid, ssid, *, history=None, mine_status="planted", events_at=None):
    """造一个 active 会话 + 可选的若干 ExecutionEvent（timestamp 为 ISO 串）。"""
    db.add(TutorSession(id=ssid, student_id=sid, pattern_id=_AS_PID, manifest={},
                        mine_status=mine_status, history=history or [], status="active"))
    for ts in (events_at or []):
        db.add(ExecutionEvent(
            id=f"ex_{_uuid.uuid4().hex[:12]}", version="v1", student_id=sid,
            session_id=ssid, pattern_id=_AS_PID, source="run", kind="OK",
            knowledge_points=[], meta={}, timestamp=ts))
    db.commit()

@test
def cleanup_只清纯空壳():
    db = TestSession()
    sid = "cl_1"
    # 系统注入的 user 消息（（系统·…）开头）不算真实发言
    sys_only = [{"role": "system", "content": "运行这段代码，看看它的行为"},
                {"role": "user", "content": "（系统·运行结果）2"}]
    _mk_active(db, sid, "empty", history=sys_only)                                   # 纯空壳 → 删
    _mk_active(db, sid, "has_msg", history=[{"role": "user", "content": "我觉得循环错了"}])  # 有真实发言 → 留
    _mk_active(db, sid, "has_run", history=sys_only, events_at=[_dt.now().isoformat()])     # 有运行记录 → 留
    _cleanup_abandoned(db, sid)
    db.commit()  # _cleanup_abandoned 只 delete 不 commit（真实调用方 create_session 负责提交）
    left = {s.id for s in db.query(TutorSession).filter_by(student_id=sid).all()}
    assert left == {"has_msg", "has_run"}, f"只该清纯空壳，实际剩：{left}"
    db.close()

@test
def cleanup_已定位不误删():
    db = TestSession()
    sid = "cl_2"
    _mk_active(db, sid, "located", history=[], mine_status="found")  # 非 planted → 不在清理范围
    _cleanup_abandoned(db, sid)
    assert db.query(TutorSession).filter_by(id="located").first() is not None, "已定位会话不该被清"
    db.close()

@test
def active_sessions_按活跃倒序且上限5():
    db = TestSession()
    sid = "as_1"
    base = _dt.now()
    for i in range(6):  # 6 个；event 时间各异，i 越大越老
        _mk_active(db, sid, f"s{i}", history=[{"role": "user", "content": "x"}],
                   events_at=[(base - _td(days=i)).isoformat()])
    sessions = get_active_sessions(sid, db=db)["sessions"]
    assert len(sessions) == 5, f"上限 5，实际 {len(sessions)}"
    assert sessions[0]["session_id"] == "s0", f"最近活跃应置顶，实际 {sessions[0]['session_id']}"
    times = [s["last_active_at"] for s in sessions]
    assert times == sorted(times, reverse=True), f"应按活跃度倒序：{times}"
    assert "s5" not in [s["session_id"] for s in sessions], "最老的应被挤出前 5"
    assert sessions[0]["name"] and sessions[0]["stage"], "应带 name/stage 供大厅展示"
    db.close()

@test
def active_sessions_无事件回退created_at():
    db = TestSession()
    sid = "as_2"
    _mk_active(db, sid, "no_ev", history=[{"role": "user", "content": "x"}])  # 无 ExecutionEvent
    sessions = get_active_sessions(sid, db=db)["sessions"]
    assert len(sessions) == 1 and sessions[0]["last_active_at"], "无事件应回退 created_at"
    db.close()

@test
def abandon_置abandoned且不删历史与事件():
    db = TestSession()
    sid = "ab_1"
    hist = [{"role": "user", "content": "我修了第 2 行"}]
    _mk_active(db, sid, "drop_me", history=hist, events_at=[_dt.now().isoformat()])
    abandon_session("drop_me", db=db)
    s = db.query(TutorSession).filter_by(id="drop_me").first()
    assert s.status == "abandoned", f"应置 abandoned，实际 {s.status}"
    assert s.history == hist, "history 不该被删"
    assert db.query(ExecutionEvent).filter_by(session_id="drop_me").count() == 1, "事件流不该被删"
    assert not get_active_sessions(sid, db=db)["sessions"], "放弃后不该再在 active-sessions"
    db.close()


# ---- sandbox ----
@test
def sandbox_基本():
    assert sandbox.run_code("print(1+1)").stdout.strip() == "2"
    assert sandbox.run_code("raise ValueError()").has_error
    assert sandbox.normalize_output("  6  ") == "6"


@test
def 提问训练_三要素评分单调():
    from app.services import question_training as q
    s0 = q._score_from_factors(False, False, False)
    s1 = q._score_from_factors(True, False, False)
    s2 = q._score_from_factors(True, True, False)
    s3 = q._score_from_factors(True, True, True)
    assert s0 < s1 < s2 < s3, (s0, s1, s2, s3)
    assert 0 <= s0 and s3 <= 100


@test
def 提问训练_空提问不调LLM得0():
    from app.services import question_training as q
    r = q.diagnose("login", "   ")
    assert r["score"] == 0 and r["degraded"] is False
    assert not r["phenomenon"] and not r["context"] and not r["expectation"]


@test
def 提问训练_fallback结构完整且不崩():
    from app.services import question_training as q
    r = q._fallback("随便写的提问")
    for k in ("phenomenon", "context", "expectation", "score", "feedback", "confidence", "degraded"):
        assert k in r, k
    assert r["degraded"] is True and r["confidence"] == 0.0


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
