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
from app.models import Event, ExecutionEvent, KnowledgeState, TutorSession
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


@test
def 提问训练_资产化落ExecutionEvent且命名空间正确():
    from app.services import question_training as q
    db = TestSession()
    r = {"phenomenon": True, "context": True, "expectation": False, "score": 66,
         "feedback": "现象上下文已清，缺预期", "confidence": 0.9, "degraded": False}
    ev = q.log_diagnosis(db, student_id="stu_qt1", scenario_id="login", prompt="登录登不上去", result=r)
    assert ev is not None
    row = db.query(ExecutionEvent).filter_by(student_id="stu_qt1").one()
    assert row.source == "qt_diagnose"
    assert row.pattern_id == "QUESTION_TRAINING"
    assert row.kind == "QT"
    assert row.knowledge_points == []                    # 空 kp → 对画像隐形
    assert row.session_id == "qtsess_stu_qt1"            # 合成 session → 对轨迹隐形
    assert row.meta["scenario_id"] == "login" and row.meta["score"] == 66
    assert row.meta["expectation"] is False
    db.close()


@test
def 提问训练_资产不进画像不进成长轨迹():
    from app.services import question_training as q
    from app.services import profile, timeline
    db = TestSession()
    # 先给该生建一个真实知识点状态 + 写若干 qt 资产
    profile.update_knowledge_state(db, student_id="stu_qt2", pattern_id="BP-X",
                                   knowledge_points=["循环"], new_state="已接触")
    for _ in range(4):
        q.log_diagnosis(db, student_id="stu_qt2", scenario_id="login", prompt="登录登不上去",
                        result={"phenomenon": True, "context": True, "expectation": False,
                                "score": 66, "feedback": "缺预期", "confidence": 0.9, "degraded": False})
    # 画像掌握度里"循环"的 evidence_count 不应被 qt 事件抬高（qt 是空 kp）
    mastery = profile.knowledge_mastery(db, "stu_qt2")
    loop = [m for m in mastery if m["kp"] == "循环"]
    assert loop and loop[0]["evidence_count"] == 0, loop
    # 成长轨迹不应出现 qt 事件
    blob = str(timeline.build_timeline(db, "stu_qt2"))
    assert "qt_diagnose" not in blob and "QUESTION_TRAINING" not in blob
    db.close()


@test
def 提问训练_短板统计样本不足返回None_够了返回最常漏():
    from app.services import question_training as q
    db = TestSession()
    # 2 条 < 门槛(3) → None
    for _ in range(2):
        q.log_diagnosis(db, student_id="stu_qt3", scenario_id="login", prompt="x",
                        result={"phenomenon": True, "context": True, "expectation": False,
                                "score": 66, "feedback": "f", "confidence": 0.9, "degraded": False})
    assert q.weakness_summary(db, "stu_qt3") is None
    # 再加 2 条（共 4 条，都缺预期）→ 返回 expectation
    for _ in range(2):
        q.log_diagnosis(db, student_id="stu_qt3", scenario_id="login", prompt="x",
                        result={"phenomenon": True, "context": True, "expectation": False,
                                "score": 66, "feedback": "f", "confidence": 0.9, "degraded": False})
    w = q.weakness_summary(db, "stu_qt3")
    assert w and w["factor"] == "expectation" and w["miss_count"] == 4
    db.close()


@test
def 提问训练_degraded与低置信不参与短板统计():
    from app.services import question_training as q
    db = TestSession()
    # 3 条都是 degraded 或低置信 → 不参与 → 样本不足 → None
    q.log_diagnosis(db, student_id="stu_qt4", scenario_id="login", prompt="x",
                    result={"phenomenon": False, "context": False, "expectation": False,
                            "score": 12, "feedback": "f", "confidence": 0.0, "degraded": True})
    for _ in range(2):
        q.log_diagnosis(db, student_id="stu_qt4", scenario_id="login", prompt="x",
                        result={"phenomenon": False, "context": False, "expectation": False,
                                "score": 12, "feedback": "f", "confidence": 0.5, "degraded": False})
    assert q.weakness_summary(db, "stu_qt4") is None


@test
def 提问训练_custom场景注册且无隐藏背景():
    from app.services import question_training as q
    assert "custom" in q.SCENARIOS and q.SCENARIOS["custom"]["brief"] == ""


@test
def 提问训练_custom资产化与预置共存且短板合并():
    from app.services import question_training as q
    db = TestSession()
    sid = "stu_custom"
    # 2 条 custom + 2 条预置，都缺预期 → 短板统计应合并到 4 条、判 expectation
    for _ in range(2):
        q.log_diagnosis(db, student_id=sid, scenario_id="custom", prompt="我自己的问题x",
                        result={"phenomenon": True, "context": True, "expectation": False,
                                "score": 66, "feedback": "f", "confidence": 0.9, "degraded": False})
    for _ in range(2):
        q.log_diagnosis(db, student_id=sid, scenario_id="login", prompt="预置场景x",
                        result={"phenomenon": True, "context": True, "expectation": False,
                                "score": 66, "feedback": "f", "confidence": 0.9, "degraded": False})
    # 资产里 custom 与预置共存
    rows = db.query(ExecutionEvent).filter_by(student_id=sid, source="qt_diagnose").all()
    sids = {(r.meta or {}).get("scenario_id") for r in rows}
    assert sids == {"custom", "login"}, sids
    # 短板统计合并 4 条
    w = q.weakness_summary(db, sid)
    assert w and w["factor"] == "expectation" and w["sample_size"] == 4
    db.close()


def _qres(p, c, e, conf=0.9, degraded=False):
    return {"phenomenon": p, "context": c, "expectation": e,
            "score": 0, "feedback": "f", "confidence": conf, "degraded": degraded}


@test
def 提问训练计分_三要素全_Prompt_Design正分点亮AI协作维度():
    from app.services import question_training as q
    from app.services import profile
    db = TestSession()
    sid = "stu_sc1"
    # 计分前：AI协作维度无分
    before = profile.get_profile(db, sid)
    ai_before = [d for d in before["dimensions"] if d["name"] == "AI协作能力"][0]
    assert ai_before["score"] is None
    # 三要素全 → +2
    ev = q.score_diagnosis(db, student_id=sid, scenario_id="login",
                           prompt="登录报NPE在第32行，期望登录成功", result=_qres(True, True, True))
    assert ev is not None and ev.capability == "Prompt_Design" and ev.delta == 2
    after = profile.get_profile(db, sid)
    ai_after = [d for d in after["dimensions"] if d["name"] == "AI协作能力"][0]
    assert ai_after["score"] is not None, after
    assert after["vector"]["Prompt_Design"]["events_count"] == 1
    db.close()


@test
def 提问训练计分_degraded和单要素不记分():
    from app.services import question_training as q
    db = TestSession()
    assert q.score_diagnosis(db, student_id="s", scenario_id="login", prompt="x",
                             result=_qres(True, True, True, degraded=True)) is None
    assert q.score_diagnosis(db, student_id="s", scenario_id="login", prompt="只有现象",
                             result=_qres(True, False, False)) is None  # 1要素→delta0→不记
    assert db.query(Event).filter_by(student_id="s", capability="Prompt_Design").count() == 0
    db.close()


@test
def 提问训练计分_纯帮我看看记负分():
    from app.services import question_training as q
    db = TestSession()
    ev = q.score_diagnosis(db, student_id="s_neg", scenario_id="login", prompt="代码报错了帮我看看",
                           result=_qres(False, False, False))
    assert ev is not None and ev.delta == -1
    db.close()


@test
def 提问训练计分_日上限6封顶():
    from app.services import question_training as q
    db = TestSession()
    sid = "stu_cap"
    # 不同提问各 +2，3 条到 +6
    for i in range(3):
        ev = q.score_diagnosis(db, student_id=sid, scenario_id="login",
                               prompt=f"完整提问版本{i}", result=_qres(True, True, True))
        assert ev is not None, i
    # 第 4 条超上限 → 不记
    assert q.score_diagnosis(db, student_id=sid, scenario_id="login",
                             prompt="完整提问版本4", result=_qres(True, True, True)) is None
    db.close()


@test
def 提问训练计分_同句今日不重复记():
    from app.services import question_training as q
    db = TestSession()
    sid = "stu_dup"
    p = "登录报NPE在第32行，期望登录成功"
    assert q.score_diagnosis(db, student_id=sid, scenario_id="login", prompt=p, result=_qres(True, True, True)) is not None
    assert q.score_diagnosis(db, student_id=sid, scenario_id="login", prompt=p, result=_qres(True, True, True)) is None
    db.close()


@test
def 提问训练计分_泛泛求代办2要素降档不记():
    from app.services import question_training as q
    db = TestSession()
    # 2要素(现象+上下文) + "帮我看看" → C档降为0、不记
    ev = q.score_diagnosis(db, student_id="s_vague", scenario_id="login",
                           prompt="登录报错了，帮我看看", result=_qres(True, True, False))
    assert ev is None
    assert db.query(Event).filter_by(student_id="s_vague", capability="Prompt_Design").count() == 0
    db.close()


@test
def 提问训练计分_泛泛求代办0要素仍负分():
    from app.services import question_training as q
    db = TestSession()
    ev = q.score_diagnosis(db, student_id="s_v0", scenario_id="login",
                           prompt="帮我看看", result=_qres(False, False, False))
    assert ev is not None and ev.delta == -1
    db.close()


@test
def 提问训练计分_明确协作请求不算泛泛():
    from app.services import question_training as q
    # 含"判断/还是"等明确协作请求 → 不被当泛泛求代办（即使有"帮我"）
    assert q._is_vague_handoff("可以帮我判断是接口返回结构问题，还是前端取值逻辑问题吗？") is False
    assert q._is_vague_handoff("帮我看看") is True
    assert q._is_vague_handoff("登录报错了，帮我看看") is True
    db = TestSession()
    # 2要素 + 明确协作请求 → 正常 +1（不降档）
    ev = q.score_diagnosis(db, student_id="s_collab", scenario_id="login",
                           prompt="登录报错，是接口问题还是前端取值问题？", result=_qres(True, True, False))
    assert ev is not None and ev.delta == 1
    db.close()


@test
def 提问训练计分_三要素完整不受泛泛影响():
    from app.services import question_training as q
    db = TestSession()
    # 三要素齐全即便带"帮我看看"也照记 +2（已是完整提问）
    ev = q.score_diagnosis(db, student_id="s_full3", scenario_id="login",
                           prompt="登录报NPE在第32行，期望登录成功，帮我看看", result=_qres(True, True, True))
    assert ev is not None and ev.delta == 2
    db.close()


@test
def 提问训练计分_低置信入库但不进画像():
    from app.services import question_training as q
    from app.models import CapabilityScore
    db = TestSession()
    sid = "stu_lowconf"
    ev = q.score_diagnosis(db, student_id=sid, scenario_id="login",
                           prompt="低置信完整提问", result=_qres(True, True, True, conf=0.5))
    assert ev is not None  # 事件入库
    # 但 confidence<0.7 不进画像分
    assert db.query(CapabilityScore).filter_by(student_id=sid, capability="Prompt_Design").first() is None
    db.close()


@test
def 状态机_修复阶段未提交时LLM不得擅自跃迁():
    """硬门回归：离开④修复只能靠 judge_fix 提交通过。LLM 在对话里填 stage_transition=⑤
    也不放行——否则代码从未判过就能走到⑤⑥甚至被标「已内化」（真实漏洞，2026-06-22 修）。"""
    from app.services import mine_engine, tutor
    from app.models import TutorSession
    orig_get, orig_load, orig_llm = mine_engine.get_pattern, mine_engine.load_patterns, tutor._call_llm
    try:
        pat = _good_candidate()
        mine_engine.get_pattern = lambda pid: {pat["id"]: pat}[pid]
        mine_engine.load_patterns = lambda: {pat["id"]: pat}
        tutor._call_llm = lambda system, history: tutor.TutorTurn(
            reply="继续", stage_transition="⑤验证", hint_level_used="L1",
            student_progressed=True, answer_begging=False, events=[])
        db = TestSession()
        sess = TutorSession(id="sess_gate1", student_id="g1", pattern_id=pat["id"],
                            manifest=mine_engine.build_manifest("g1", pat), history=[],
                            stage="④修复", mine_status="found")
        db.add(sess); db.commit()
        tutor.run_turn(db, sess, "改个边界就行")
        assert sess.stage == "④修复", f"未提交不该离开④，实际到了 {sess.stage}"
        assert sess.mine_status == "found", sess.mine_status
        db.close()
    finally:
        mine_engine.get_pattern, mine_engine.load_patterns, tutor._call_llm = orig_get, orig_load, orig_llm


@test
def 状态机_提交通过后可正常进验证():
    """对照：mine_status=fixed（提交已判过）时，④→⑤ 的跃迁正常放行，不被新门误伤。"""
    from app.services import mine_engine, tutor
    from app.models import TutorSession
    orig_get, orig_load, orig_llm = mine_engine.get_pattern, mine_engine.load_patterns, tutor._call_llm
    try:
        pat = _good_candidate()
        mine_engine.get_pattern = lambda pid: {pat["id"]: pat}[pid]
        mine_engine.load_patterns = lambda: {pat["id"]: pat}
        tutor._call_llm = lambda system, history: tutor.TutorTurn(
            reply="继续", stage_transition="⑤验证", hint_level_used="L1",
            student_progressed=True, answer_begging=False, events=[])
        db = TestSession()
        sess = TutorSession(id="sess_gate2", student_id="g2", pattern_id=pat["id"],
                            manifest=mine_engine.build_manifest("g2", pat), history=[],
                            stage="④修复", mine_status="fixed")  # 已提交判过
        db.add(sess); db.commit()
        tutor.run_turn(db, sess, "我想测空列表")
        assert sess.stage == "⑤验证", f"已 fixed 应可进⑤，实际 {sess.stage}"
        db.close()
    finally:
        mine_engine.get_pattern, mine_engine.load_patterns, tutor._call_llm = orig_get, orig_load, orig_llm


# ════════ 导师纯规则函数（无 LLM、无 DB，最便宜的回归网）════════

@test
def 受挫检测_学生本人受挫与程序卡住要分开():
    from app.services import tutor
    # 学生本人受挫 → True
    for s in ["我不会", "完全没思路", "太难了", "想放弃", "给个提示", "啊啊啊", "我卡住了"]:
        assert tutor.detect_frustration(s), f"应判受挫: {s}"
    # 描述程序卡住（不是本人受挫）→ False
    for s in ["程序卡住了跑不完", "代码一直在循环卡住", "运行卡住"]:
        assert not tutor.detect_frustration(s), f"程序卡死≠学生受挫: {s}"
    # 负向断言别误伤：会不会/知不知道 不算受挫
    for s in ["会不会越界", "我知不知道得测一下", "这样对不对"]:
        assert not tutor.detect_frustration(s), f"不该误判受挫: {s}"


@test
def 错误签名识别_命中返回剧本_未命中None():
    from app.services import tutor
    sig, pb = tutor.detect_error_signature("我猜会报 IndexError")
    assert sig == "IndexError" and "meaning" in pb
    assert tutor.detect_error_signature("不知道哪里错") is None


@test
def 定位判定_引用雷行或点行号才算():
    from app.services import mine_engine, tutor
    orig = mine_engine.get_pattern
    try:
        pat = _good_candidate()  # 雷在第 2 行：return a[3]
        mine_engine.get_pattern = lambda pid: {pat["id"]: pat}[pid]
        assert tutor.message_points_at_mine("我觉得 return a[3] 有问题", pat["id"])
        assert tutor.message_points_at_mine("第 2 行不对吧", pat["id"])
        assert not tutor.message_points_at_mine("不知道在哪", pat["id"])
    finally:
        mine_engine.get_pattern = orig


@test
def 边界解释判定_要同时有边界输入和预期():
    from app.services import tutor
    assert tutor.message_explains_boundary_test("空列表传进去，预期返回 None")
    assert not tutor.message_explains_boundary_test("空列表试试")      # 缺预期
    assert not tutor.message_explains_boundary_test("应该返回正确结果")  # 缺具体边界输入


@test
def 内化实质性_纯表态不算_含机制才算():
    from app.services import tutor
    for s in ["我懂了", "好的", "嗯嗯", "以后注意"]:
        assert not tutor.is_substantive(s), f"纯表态不该算: {s}"
    assert tutor.is_substantive("因为下标从0数，长度3时最大下标是2，访问3就越界了")


# ════════ run_turn 状态机跃迁（stub LLM，覆盖规则跃迁与硬门）════════

def _stub_turn(tutor, **kw):
    base = dict(reply="嗯", stage_transition=None, hint_level_used="L0",
                student_progressed=True, answer_begging=False, events=[])
    base.update(kw)
    return lambda system, history: tutor.TutorTurn(**base)

def _arena_session(tutor, mine_engine, *, stage, mine_status="planted"):
    pat = _good_candidate()
    mine_engine.get_pattern = lambda pid: {pat["id"]: pat}[pid]
    mine_engine.load_patterns = lambda: {pat["id"]: pat}
    from app.models import TutorSession
    db = TestSession()
    sess = TutorSession(id=f"s_{stage}_{__import__('uuid').uuid4().hex[:6]}", student_id="rt1", pattern_id=pat["id"],
                        manifest=mine_engine.build_manifest("rt1", pat), history=[],
                        stage=stage, mine_status=mine_status)
    db.add(sess); db.commit()
    return db, sess, pat


@test
def 跃迁_发现阶段贴出报错签名自动进定位():
    from app.services import mine_engine, tutor
    o1, o2, o3 = mine_engine.get_pattern, mine_engine.load_patterns, tutor._call_llm
    try:
        tutor._call_llm = _stub_turn(tutor)  # LLM 不报跃迁
        db, sess, pat = _arena_session(tutor, mine_engine, stage="①发现")
        tutor.run_turn(db, sess, "它会报 IndexError 吧")
        assert sess.stage == "②定位", sess.stage  # 规则层据报错签名自动跃迁
        db.close()
    finally:
        mine_engine.get_pattern, mine_engine.load_patterns, tutor._call_llm = o1, o2, o3


@test
def 跃迁_定位阶段指认雷行自动进归因且雷标found():
    from app.services import mine_engine, tutor
    o1, o2, o3 = mine_engine.get_pattern, mine_engine.load_patterns, tutor._call_llm
    try:
        tutor._call_llm = _stub_turn(tutor)
        db, sess, pat = _arena_session(tutor, mine_engine, stage="②定位")
        tutor.run_turn(db, sess, "问题在 return a[3] 这行")
        assert sess.stage == "③归因", sess.stage
        assert sess.mine_status == "found", sess.mine_status
        assert sess.attribution_step == "variable_trace"
        db.close()
    finally:
        mine_engine.get_pattern, mine_engine.load_patterns, tutor._call_llm = o1, o2, o3


@test
def 跃迁_内化三轴达标则升级已内化并结束会话():
    from app.services import mine_engine, profile, tutor
    from app.models import KnowledgeState
    o1, o2, o3 = mine_engine.get_pattern, mine_engine.load_patterns, tutor._call_llm
    try:
        tutor._call_llm = _stub_turn(
            tutor, internalization=tutor.InternalizationScore(cause=True, locate=True, prevent=False))
        db, sess, pat = _arena_session(tutor, mine_engine, stage="⑥内化", mine_status="fixed")
        tutor.run_turn(db, sess, "因为下标越界，定位靠看报错行和追踪变量，下次先查 range 边界")
        assert sess.mine_status == "internalized", sess.mine_status
        assert sess.status == "completed", sess.status
        ks = db.get(KnowledgeState, ("rt1", pat["id"]))
        assert ks and ks.state == "已内化", ks
        db.close()
    finally:
        mine_engine.get_pattern, mine_engine.load_patterns, tutor._call_llm = o1, o2, o3


# ════════ 算分 / 画像（profile）════════

@test
def 算分_冷启动加倍且封顶100():
    from app.services import event_engine
    from app.models import CapabilityScore
    db = TestSession()
    # INITIAL=30；冷启动×2（events<10）；规则事件 conf=1.0 → 每条 +3×3×2 = +18
    for _ in range(4):
        event_engine.emit(db, student_id="sc_up", session_id="x", capability="Independent_Debug",
                          delta=3, producer="rule", evidence={"summary": "fix"})
    r = db.get(CapabilityScore, ("sc_up", "Independent_Debug"))
    assert r.score == 100.0, r.score        # 30→48→66→84→100，4 条即封顶
    assert r.events_count == 4
    db.close()


@test
def 算分_负向事件下探不破0():
    from app.services import event_engine
    from app.models import CapabilityScore
    db = TestSession()
    for _ in range(2):  # 30 -18 -18 → 钳到 0
        event_engine.emit(db, student_id="sc_dn", session_id="x", capability="Independent_Debug",
                          delta=-3, producer="rule", evidence={"summary": "neg"})
    r = db.get(CapabilityScore, ("sc_dn", "Independent_Debug"))
    assert r.score == 0.0, r.score
    db.close()


@test
def 算分_低置信LLM事件入库但不进分():
    from app.services import event_engine
    from app.models import CapabilityScore, Event
    db = TestSession()
    event_engine.emit(db, student_id="sc_lc", session_id="x", capability="Root_Cause_Reasoning",
                      delta=3, producer="llm_judge", confidence=0.5, evidence={"summary": "弱证据"})
    assert db.query(Event).filter_by(student_id="sc_lc").count() == 1          # 事件入库
    assert db.get(CapabilityScore, ("sc_lc", "Root_Cause_Reasoning")) is None  # 但不进画像分
    db.close()


@test
def 掌握度_状态映射与薄弱判定():
    from app.services import profile
    db = TestSession()
    sid = "km1"
    profile.update_knowledge_state(db, student_id=sid, pattern_id="P_A",
                                   knowledge_points=["kpA"], new_state="已内化")
    profile.update_knowledge_state(db, student_id=sid, pattern_id="P_B",
                                   knowledge_points=["kpB"], new_state="已解决")
    profile.update_knowledge_state(db, student_id=sid, pattern_id="P_C",
                                   knowledge_points=["kpC"], new_state="已接触")
    m = {x["kp"]: x for x in profile.knowledge_mastery(db, sid)}
    assert m["kpA"]["mastery"] == "掌握" and m["kpA"]["weak"] is False
    assert m["kpB"]["mastery"] == "在学" and m["kpB"]["weak"] is True   # 已解决→建议内化
    assert m["kpC"]["mastery"] == "生疏" and m["kpC"]["weak"] is True   # 已接触→还没真正解决
    db.close()


# ════════ AI 共脑调试 coop（B0，不连 LLM 的部分）════════

@test
def coop_建会话_mode为coop且伪pattern_id():
    from app.services import coop
    db = TestSession()
    out = coop.start(db, "co1", "off_by_one")
    assert out["sample_id"] == "off_by_one" and out["code"]
    s = db.get(TutorSession, out["session_id"])
    assert (s.manifest or {}).get("mode") == "coop"
    assert s.pattern_id == "coop_off_by_one"
    assert s.history and s.history[0]["role"] == "user"   # 首条=样本求助
    db.close()


@test
def coop_非法样本回退第一个():
    from app.services import coop
    db = TestSession()
    out = coop.start(db, "co2", "不存在的样本")
    assert out["sample_id"] in coop.SAMPLES
    db.close()


@test
def coop_run落ExecutionEvent_mode_coop且不查pattern():
    from app.services import coop
    from app.models import ExecutionEvent
    db = TestSession()
    out = coop.start(db, "co3", "off_by_one")
    # 跑一段真代码（不依赖任何 pattern，伪 id 不会崩）
    r = coop.run(db, out["session_id"], "print(1+1)")
    assert r["stdout"].strip() == "2"
    ev = db.query(ExecutionEvent).filter_by(session_id=out["session_id"]).one()
    assert ev.knowledge_points == []                 # 对画像天然隐形
    assert (ev.meta or {}).get("mode") == "coop"
    db.close()


@test
def coop_run把真实结果注入对话():
    from app.services import coop, tutor
    db = TestSession()
    out = coop.start(db, "co4", "off_by_one")
    coop.run(db, out["session_id"], "print(42)")
    s = db.get(TutorSession, out["session_id"])
    notes = [m for m in s.history if m["content"].startswith(tutor.RUN_RESULT_PREFIX)]
    assert len(notes) == 1 and "42" in notes[0]["content"]
    db.close()


@test
def coop_resolve标completed():
    from app.services import coop
    db = TestSession()
    out = coop.start(db, "co5", "off_by_one")
    assert coop.resolve(db, out["session_id"])["status"] == "completed"
    s = db.get(TutorSession, out["session_id"])
    assert s.status == "completed"
    db.close()


@test
def coop_防污染_不进成长轨迹():
    from app.services import coop, timeline
    db = TestSession()
    out = coop.start(db, "co6", "off_by_one")
    coop.run(db, out["session_id"], "print(1)")
    tl = timeline.build_timeline(db, "co6")
    assert tl["episodes"] == []        # coop 会话被 build_timeline 排除
    db.close()


@test
def coop_防污染_不抬高知识点掌握度():
    from app.services import coop, profile
    db = TestSession()
    out = coop.start(db, "co7", "off_by_one")
    coop.run(db, out["session_id"], "print(1)")
    # coop 的 ExecutionEvent knowledge_points=[] → 不产生任何 kp 掌握度
    assert profile.knowledge_mastery(db, "co7") == []
    db.close()


@test
def coop_错误session_id返回None():
    from app.services import coop
    db = TestSession()
    assert coop.get(db, "不存在") is None
    assert coop.run(db, "不存在", "print(1)") is None
    assert coop.message(db, "不存在", "hi") is None
    assert coop.resolve(db, "不存在") is None
    db.close()


@test
def coop_自带代码_建custom会话且存code():
    from app.services import coop
    db = TestSession()
    out = coop.start_custom(db, "cc1", "print('hi')\n", "它不输出东西")
    assert out["sample_id"] is None and out["title"] == "我的代码"
    s = db.get(TutorSession, out["session_id"])
    assert (s.manifest or {}).get("custom") is True
    assert s.pattern_id == "coop_custom"
    assert s.manifest["code"] == "print('hi')"       # code 存进 manifest，刷新可恢复
    assert s.history[0]["content"] == "它不输出东西"   # 描述作首条求助
    db.close()


@test
def coop_自带代码_空代码返回None_超长截断():
    from app.services import coop
    db = TestSession()
    assert coop.start_custom(db, "cc2", "   ") is None       # 空代码不建会话
    big = "x = 1\n" * 5000                                   # 远超上限
    out = coop.start_custom(db, "cc2", big)
    s = db.get(TutorSession, out["session_id"])
    assert len(s.manifest["code"]) == coop.MAX_CODE_LEN      # 截断到上限
    db.close()


@test
def coop_自带代码_无描述给默认求助():
    from app.services import coop
    db = TestSession()
    out = coop.start_custom(db, "cc3", "print(1)")
    assert "看看" in out["ask"]    # 没填描述 → 默认一句求助（导师仍会主动问预期）
    db.close()


@test
def coop_自带代码_get恢复manifest里的code():
    from app.services import coop
    db = TestSession()
    out = coop.start_custom(db, "cc4", "a = 42\nprint(a)")
    got = coop.get(db, out["session_id"])
    assert got["code"] == "a = 42\nprint(a)" and got["title"] == "我的代码"
    db.close()


@test
def coop_自带代码_防污染不进轨迹():
    from app.services import coop, timeline
    db = TestSession()
    out = coop.start_custom(db, "cc5", "print(1)")
    coop.run(db, out["session_id"], "print(1)")
    assert timeline.build_timeline(db, "cc5")["episodes"] == []
    db.close()


@test
def coop_get不能拿到闯关会话():
    """coop 的 get 只认 mode=coop 会话，普通闯关 session 一律 None（隔离）。"""
    from app.services import coop
    db = TestSession()
    s = TutorSession(id="normal_sess", student_id="co8", pattern_id="BP-X",
                     manifest={"mode": "debug", "mines": [{}]}, history=[])
    db.add(s); db.commit()
    assert coop.get(db, "normal_sess") is None
    db.close()


@test
def coopB2_埋点_resolve记协作信号且不进画像():
    from app.services import coop
    from app.models import ExecutionEvent, CapabilityScore, Event
    db = TestSession()
    out = coop.start(db, "b2a", "off_by_one")
    coop.run(db, out["session_id"], "print(1)")      # 真实动手运行一次
    coop.resolve(db, out["session_id"])
    sig = db.query(ExecutionEvent).filter_by(session_id=out["session_id"], source="coop_resolve").all()
    assert len(sig) == 1 and sig[0].kind == "COLLAB"
    assert sig[0].meta["collab"]["runs"] == 1
    assert sig[0].knowledge_points == []
    # 埋点不计分：无能力分、无能力事件
    assert db.query(CapabilityScore).filter_by(student_id="b2a").count() == 0
    assert db.query(Event).filter_by(student_id="b2a").count() == 0
    db.close()


@test
def coopB2_埋点_没动手运行不记():
    from app.services import coop
    from app.models import ExecutionEvent
    db = TestSession()
    out = coop.start(db, "b2b", "off_by_one")
    coop.resolve(db, out["session_id"])    # 没点过运行 → 不算有效协作
    assert db.query(ExecutionEvent).filter_by(session_id=out["session_id"], source="coop_resolve").count() == 0
    db.close()


@test
def coopB2_埋点_不进成长轨迹():
    from app.services import coop, timeline
    db = TestSession()
    out = coop.start(db, "b2c", "off_by_one")
    coop.run(db, out["session_id"], "print(1)")
    coop.resolve(db, out["session_id"])
    assert timeline.build_timeline(db, "b2c")["episodes"] == []
    db.close()


@test
def 画像_维度带覆盖度trained_total():
    from app.services import event_engine, profile
    db = TestSession()
    # 只练 1 个 Debug 子能力（共 5 个）→ trained=1 total=5，治 #18 虚高的语境
    for _ in range(3):
        event_engine.emit(db, student_id="cov1", session_id="x", capability="Independent_Debug",
                          delta=3, producer="rule", evidence={"summary": "fix"})
    deb = [d for d in profile.get_profile(db, "cov1")["dimensions"] if d["name"] == "Debug能力"][0]
    assert deb["trained"] == 1 and deb["total"] == 5, deb
    ai = [d for d in profile.get_profile(db, "cov1")["dimensions"] if d["name"] == "AI协作能力"][0]
    assert ai["trained"] == 0 and ai["total"] == 3, ai
    db.close()


@test
def 灵犀_新用户无历史_有活动后有天数():
    from app.services import coop, presence
    db = TestSession()
    assert presence.presence_signals(db, "ling1") == {
        "has_history": False, "last_active_at": None, "days_since": None}
    # 建个 coop 会话（产生 TutorSession）→ 算"来过"
    coop.start(db, "ling1", "off_by_one")
    p = presence.presence_signals(db, "ling1")
    assert p["has_history"] is True and p["days_since"] == 0   # 刚活动 → 0 天
    db.close()


# ════════ judge_fix 剩余分支（WA 答案错 / HANG 死循环）════════

@test
def judge_跑通但输出不符判WA():
    from app.services import mine_engine
    pat = _good_candidate()   # expected_output = "2"
    orig = mine_engine.get_pattern
    try:
        mine_engine.get_pattern = lambda pid: {pat["id"]: pat}[pid]
        # 能跑通、不报错，但输出 1 ≠ 期望 2 → WA
        r = mine_engine.judge_fix(pat["id"], "def f(a):\n    return a[0]\nprint(f([1, 2]))\n")
        assert r["kind"] == "WA" and r["passed"] is False, r
    finally:
        mine_engine.get_pattern = orig


@test
def judge_死循环判HANG():
    from app.services import mine_engine
    pat = _good_candidate()
    orig = mine_engine.get_pattern
    try:
        mine_engine.get_pattern = lambda pid: {pat["id"]: pat}[pid]
        r = mine_engine.judge_fix(pat["id"], "while True:\n    pass\n")   # 超时（真跑约 4s）
        assert r["kind"] == "HANG" and r["passed"] is False, r
    finally:
        mine_engine.get_pattern = orig


# ════════ run_turn 状态机剩余分支（③归因步进 / 止损降档）════════

@test
def 跃迁_归因步进_变量追踪到规则对照():
    from app.services import mine_engine, tutor
    o1, o2, o3 = mine_engine.get_pattern, mine_engine.load_patterns, tutor._call_llm
    try:
        # 学生答对当前步（variable_trace）且有进展 → 步进到 rule_compare
        tutor._call_llm = _stub_turn(tutor, attribution_step="variable_trace", student_progressed=True)
        db, sess, pat = _arena_session(tutor, mine_engine, stage="③归因")
        tutor.run_turn(db, sess, "len 是 3，i 会取到 0,1,2,3")
        assert sess.attribution_step == "rule_compare", sess.attribution_step
        db.close()
    finally:
        mine_engine.get_pattern, mine_engine.load_patterns, tutor._call_llm = o1, o2, o3


@test
def 止损_受挫时提示级别升一格():
    from app.services import mine_engine, tutor
    o1, o2, o3 = mine_engine.get_pattern, mine_engine.load_patterns, tutor._call_llm
    try:
        tutor._call_llm = _stub_turn(tutor, hint_level_used="L0", student_progressed=False)
        db, sess, pat = _arena_session(tutor, mine_engine, stage="②定位")
        assert sess.hint_level == "L0"
        tutor.run_turn(db, sess, "我不会，完全没思路")   # 受挫 → 止损共情层升一格
        assert sess.hint_level == "L1", sess.hint_level
        db.close()
    finally:
        mine_engine.get_pattern, mine_engine.load_patterns, tutor._call_llm = o1, o2, o3


@test
def coop_样本库七道且每道可建会话():
    from app.services import coop
    assert len(coop.SAMPLES) == 7, len(coop.SAMPLES)
    assert len(coop.list_samples()) == 7
    db = TestSession()
    for sid in coop.SAMPLES:
        out = coop.start(db, "samp", sid)
        assert out["sample_id"] == sid and out["code"] and out["title"] and out["ask"], sid
    db.close()


@test
def 报错翻译_各错误返回中文_无报错返回None():
    from app.services import tutor
    assert "死循环" in (tutor.explain_error("HANG", "") or "")
    assert tutor.explain_error("RE", "IndexError: list index out of range")
    assert "下一步" in tutor.explain_error("RE", "KeyError: 'x'")   # 翻译含"怎么查"方向
    assert tutor.explain_error("OK", "") is None                 # 没报错不硬塞
    assert tutor.explain_error("RE", "完全不认识的乱码") is None   # 识别不了返回 None


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
