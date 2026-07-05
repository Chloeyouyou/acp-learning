"""过程化 · 代码快照（M2）。每次 run/submit 记下学生当时的代码 + 相对变化。

把事件流的「结果链」（每次执行 RE/WA/OK）补成「代码链」（当时的代码本身）：
让解题过程可逐版回放，也能 diff 分析——学生是「盯着雷行定向改」还是「到处盲改碰运气」。

纯 append：只 INSERT CodeSnapshot，不改任何既有表/事件流。可被回放（M3）消费。
"""

import difflib
import re
import uuid

from sqlalchemy.orm import Session

from ..models import CodeSnapshot, SessionMessage, now
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


def record_message(db: Session, session_id: str, role: str, content: str,
                   kind: str = "chat") -> SessionMessage:
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
        created_at=now(),
    )
    db.add(msg)
    db.flush()   # 同事务内连记多条时 seq 正确续上
    return msg
