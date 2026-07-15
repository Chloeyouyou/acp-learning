"""过程化 · 代码快照（M2）。每次 run/submit 记下学生当时的代码 + 相对变化。

把事件流的「结果链」（每次执行 RE/WA/OK）补成「代码链」（当时的代码本身）：
让解题过程可逐版回放，也能 diff 分析——学生是「盯着雷行定向改」还是「到处盲改碰运气」。

纯 append：只 INSERT CodeSnapshot，不改任何既有表/事件流。可被回放（M3）消费。
"""

import difflib
import re
import uuid

from sqlalchemy.orm import Session

from ..models import CodeSnapshot, ExecutionEvent, SessionMessage, TutorSession, now
from . import mine_engine

_norm = lambda s: re.sub(r"\s+", "", s or "")


def _lines_changed(prev_code: str | None, cur_code: str) -> int:
    """相对上一版改动了多少行。首版（无上一版）记为非空行数（全算新增）。"""
    cur_lines = cur_code.splitlines()
    if prev_code is None:
        return sum(1 for ln in cur_lines if ln.strip())
    sm = difflib.SequenceMatcher(a=prev_code.splitlines(), b=cur_lines)
    return sum(max(i2 - i1, j2 - j1)
               for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal")


def _touched_mine_line(buggy_code: str | None, mine_line_no: int | None, cur_code: str) -> bool | None:
    """学生是否动过「雷行」——原始带雷代码的雷行文本，是否已不再原样出现在当前代码里。
    无 pattern（coop）或无雷行信息时返回 None（无从判断）。行号会因编辑漂移，故按文本存在性判定。"""
    if not buggy_code or not mine_line_no:
        return None
    buggy_lines = buggy_code.splitlines()
    if not (1 <= mine_line_no <= len(buggy_lines)):
        return None
    orig = _norm(buggy_lines[mine_line_no - 1]).rstrip(":")
    if not orig:
        return None
    return orig not in _norm(cur_code)   # 原样还在 → 没动；不在 → 动过


def compute_diff_stats(prev_code: str | None, cur_code: str,
                       buggy_code: str | None = None, mine_line_no: int | None = None) -> dict:
    return {
        "lines_changed": _lines_changed(prev_code, cur_code),
        "touched_mine_line": _touched_mine_line(buggy_code, mine_line_no, cur_code),
    }


def diff_summary(diff_stats: dict) -> str:
    """把一次提交的 diff_stats 转成给导师看的「改动分析」——区分盲改 vs 定向改。
    只给导师做引导上下文，不直接给学生。touched_mine_line=None（coop/无雷信息）时返回空串。"""
    touched = (diff_stats or {}).get("touched_mine_line")
    if touched is None:
        return ""
    lines = (diff_stats or {}).get("lines_changed", 0)
    spread = "（而且一次改了较多行，像在多处试探）" if lines and lines >= 5 else ""
    if touched:
        return f"学生这次改到了关键的那一行，但结果仍不对——方向对了、具体改法还没对{spread}。"
    return f"学生这次的改动没落在真正出问题的那一行上，还在别处改{spread}。"


def record_snapshot(db: Session, session, code: str, execution_event_id: str | None = None) -> CodeSnapshot:
    """记一条代码快照（append-only）。seq 会话内递增；diff_stats 相对上一快照 + 相对原始带雷码。
    不 commit——由调用方随本次 run/submit 的事务一起提交。"""
    prev = (db.query(CodeSnapshot).filter_by(session_id=session.id)
            .order_by(CodeSnapshot.seq.desc()).first())
    buggy_code = mine_line_no = None
    try:
        pat = mine_engine.get_pattern(session.pattern_id)
        buggy_code = pat.get("buggy_code")
        mine_line_no = (pat.get("mine_location") or {}).get("line")
    except KeyError:
        pass   # coop / 伪 pattern：touched_mine_line 记 None
    snap = CodeSnapshot(
        id=f"cs_{uuid.uuid4().hex[:16]}",
        session_id=session.id,
        execution_event_id=execution_event_id,
        seq=(prev.seq + 1) if prev else 1,
        code=code,
        diff_stats=compute_diff_stats(prev.code if prev else None, code, buggy_code, mine_line_no),
        timestamp=now(),
    )
    db.add(snap)
    db.flush()   # 立即入库（不提交）——同一事务内再记快照时 seq 能正确续上（会话 autoflush=False）
    return snap


_RESULT_LABEL = {"OK": "通过", "RE": "报错", "WA": "结果不对", "HANG": "超时"}


def _mark(marker_type: str, title: str, detail: str) -> dict:
    return {"type": marker_type, "title": title, "detail": detail}


def derive_turning_points(code_steps: list[dict]) -> list[dict]:
    """从代码/执行事实中标注解题转折点；不写库，可由任意时刻重放重算。"""
    had_failure = False
    targeted_seen = False
    breakthrough_seen = False
    previous_family = None
    turning_points: list[dict] = []

    for step in code_steps:
        annotations: list[dict] = []
        result = step.get("result")
        family = step.get("error_family") or result
        touched = (step.get("diff_stats") or {}).get("touched_mine_line")
        failed_before = had_failure

        if result and result != "OK" and not had_failure:
            annotations.append(_mark(
                "first_failure", "第一次拿到真实反馈",
                f"第 {step['version']} 版运行结果是{step.get('result_label') or result}，问题从猜测变成了可观察事实。",
            ))

        if failed_before and touched is True and not targeted_seen:
            targeted_seen = True
            annotations.append(_mark(
                "targeted_change", "修改开始对准关键位置",
                f"第 {step['version']} 版第一次在失败后动到了关键行，调试从试探转向定向验证。",
            ))

        if (failed_before and previous_family and family and family != previous_family
                and result != "OK"):
            annotations.append(_mark(
                "error_changed", "错误形态发生变化",
                f"真实反馈从 {previous_family} 变为 {family}，说明这次修改改变了程序的执行路径。",
            ))

        if result == "OK" and failed_before and not breakthrough_seen:
            breakthrough_seen = True
            annotations.append(_mark(
                "breakthrough", "这里出现了关键突破",
                f"第 {step['version']} 版从连续失败走到通过，形成了“观察—修改—验证”的闭环。",
            ))

        if result and result != "OK":
            had_failure = True
        if family:
            previous_family = family

        step["annotations"] = annotations
        for marker in annotations:
            turning_points.append({"version": step["version"], **marker})

    return turning_points


_OBSERVATION_MARK = "【观察记录】"
_SUMMARY_MARK = "【思考总结】"


def derive_replay_mainline(steps: list[dict]) -> int:
    """给完整回放步骤加上可重算的主线标记，返回主线步数。

    原始 steps 一步不删；学生端和教师端只需按 ``mainline`` 过滤，就能先看同一条
    “真实动作—关键转折—学生总结”主线，需要审计时再展开完整流水。
    """
    code_indexes = [i for i, step in enumerate(steps) if step.get("kind") == "code"]
    first_code = code_indexes[0] if code_indexes else None
    last_code = code_indexes[-1] if code_indexes else None
    selected = 0

    for index, step in enumerate(steps):
        reasons: list[str] = []
        if step.get("kind") == "code":
            if index == first_code:
                reasons.append("first_execution")
            if step.get("annotations"):
                reasons.append("turning_point")
            if index == last_code:
                reasons.append("latest_execution")
        else:
            content = (step.get("content") or "").strip()
            if step.get("role") == "student" and content.startswith(_OBSERVATION_MARK):
                reasons.append("student_observation")
            if step.get("role") == "student" and content.startswith(_SUMMARY_MARK):
                reasons.append("student_summary")
            strategy = (step.get("meta") or {}).get("teaching_strategy") or {}
            if step.get("role") == "tutor" and strategy.get("route_changed"):
                reasons.append("teaching_route_changed")

        step["mainline"] = bool(reasons)
        step["mainline_reasons"] = reasons
        if reasons:
            selected += 1

    return selected


def teaching_metrics(db: Session, session_id: str) -> dict:
    """由导师消息 meta 重放教学策略效果。旧会话没有 meta 时返回全零，不猜测。"""
    messages = (db.query(SessionMessage).filter_by(session_id=session_id, role="tutor")
                .order_by(SessionMessage.seq).all())
    decisions = []
    for message in messages:
        meta = message.meta or {}
        if meta.get("teaching_strategy"):
            decisions.append(meta)

    confusion_indexes = [i for i, meta in enumerate(decisions) if meta.get("confusion_detected")]
    recovered = 0
    for index in confusion_indexes:
        # “恢复”只看随后两轮，且使用已经落库的规则/LLM进展判断，不重新猜学生情绪。
        following = decisions[index + 1:index + 3]
        if any(m.get("student_progressed") or m.get("stage_after") != m.get("stage_before")
               for m in following):
            recovered += 1

    routes: dict[str, int] = {}
    for meta in decisions:
        route = (meta.get("teaching_strategy") or {}).get("explanation_route")
        if route:
            routes[route] = routes.get(route, 0) + 1

    confusion_turns = len(confusion_indexes)
    return {
        "tutor_turns": len(decisions),
        "confusion_turns": confusion_turns,
        "route_changed_turns": sum(1 for m in decisions
                                   if (m.get("teaching_strategy") or {}).get("route_changed")),
        "knowledge_gap_turns": sum(1 for m in decisions
                                  if (m.get("teaching_strategy") or {}).get("knowledge_gap")),
        "recovered_within_two_turns": recovered,
        "recovery_rate": round(recovered / confusion_turns, 3) if confusion_turns else None,
        "routes": routes,
    }


def build_replay(db: Session, session_id: str) -> dict | None:
    """过程回放（M3）：把 code_snapshots + session_messages 按时间戳合并成一条可步进的时间线。

    让学生/老师逐步回看「代码怎么一版版改、对话怎么推进、每次运行/提交什么结果」——
    把不可见的解题过程变成可见的故事。纯派生只读。会话不存在返回 None。
    """
    session = db.get(TutorSession, session_id)
    if session is None:
        return None

    snaps = (db.query(CodeSnapshot).filter_by(session_id=session_id)
             .order_by(CodeSnapshot.seq).all())
    msgs = (db.query(SessionMessage).filter_by(session_id=session_id)
            .order_by(SessionMessage.seq).all())
    ev_by_id = {e.id: e for e in
                db.query(ExecutionEvent).filter_by(session_id=session_id).all()}

    steps: list[dict] = []
    code_steps: list[dict] = []
    for i, s in enumerate(snaps):
        ev = ev_by_id.get(s.execution_event_id)
        code_step = {
            "kind": "code",
            "at": s.timestamp,
            "version": i + 1,                       # 第几版代码（回放步进用）
            "code": s.code,
            "diff_stats": s.diff_stats or {},
            "source": ev.source if ev else None,    # run / submit
            "result": ev.kind if ev else None,      # OK/RE/WA/HANG
            "result_label": _RESULT_LABEL.get(ev.kind) if ev else None,
            "error_family": ev.error_family if ev else None,
            # Resource Gateway 亮点落地：前端回放可用 call_id 把动作、代码与能力事件串起来。
            "action_context": ((ev.meta or {}).get("action_context") if ev else None),
        }
        code_steps.append(code_step)
        steps.append(code_step)
    turning_points = derive_turning_points(code_steps)
    for m in msgs:
        steps.append({
            "kind": "msg",
            "at": m.created_at,
            "role": m.role,                          # student / tutor / system
            "msg_kind": m.kind,                      # chat / run_result / submit / tutor_opening
            "content": m.content,
            "meta": m.meta or {},
        })
    steps.sort(key=lambda x: x["at"])
    mainline_steps = derive_replay_mainline(steps)

    try:
        pat = mine_engine.get_pattern(session.pattern_id)
        pattern_name = pat.get("name", session.pattern_id)
    except KeyError:
        pattern_name = session.pattern_id   # coop / 伪 pattern
    return {
        "session_id": session_id,
        "pattern_id": session.pattern_id,
        "pattern_name": pattern_name,
        "mine_status": session.mine_status,
        "code_versions": len(snaps),
        "turning_points": turning_points,
        "teaching_metrics": teaching_metrics(db, session_id),
        "mainline_steps": mainline_steps,
        "steps": steps,
    }


def record_message(db: Session, session_id: str, role: str, content: str,
                   kind: str = "chat", meta: dict | None = None) -> SessionMessage:
    """记一条会话消息到 append-only 时间线（供 M3 回放）。seq 会话内递增；不 commit。
    与 history 并行的「写新」——history 读写不动，此表只增不删、保留发生过的每一步。"""
    prev_seq = (db.query(SessionMessage.seq).filter_by(session_id=session_id)
                .order_by(SessionMessage.seq.desc()).first())
    msg = SessionMessage(
        id=f"sm_{uuid.uuid4().hex[:16]}",
        session_id=session_id,
        seq=(prev_seq[0] + 1) if prev_seq else 1,
        role=role,
        kind=kind,
        content=content,
        meta=dict(meta or {}),
        created_at=now(),
    )
    db.add(msg)
    db.flush()   # 同事务内连记多条时 seq 正确续上
    return msg
