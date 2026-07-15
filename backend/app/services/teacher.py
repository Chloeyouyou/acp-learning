"""教师端总览（M4）· 纯派生只读。

给老师一页看全班：每个学生做到哪、解决/内化几题、最近活跃、正卡在哪。
复用现有派生（knowledge_states / presence / active-session），零新表。
班级：class_id 现阶段多为空，传了就按班过滤，不传看全体。
"""

from sqlalchemy.orm import Session

from ..models import KnowledgeState, Student, TutorSession
from . import mine_engine, presence, process


def _current_level(db: Session, student_id: str) -> dict | None:
    """该生正在进行的一关（最新的 active、非 coop 会话）：题名 + 阶段。无则 None。"""
    actives = (db.query(TutorSession)
               .filter_by(student_id=student_id, status="active")
               .order_by(TutorSession.updated_at.desc()).all())
    for s in actives:
        if s.is_coop:
            continue
        try:
            name = mine_engine.get_pattern(s.pattern_id).get("name", s.pattern_id)
        except KeyError:
            name = s.pattern_id
        return {
            "session_id": s.id,
            "pattern_id": s.pattern_id,
            "pattern_name": name,
            "stage": s.stage,
        }
    return None


def _pattern_name(pattern_id: str) -> str:
    try:
        return mine_engine.get_pattern(pattern_id).get("name", pattern_id)
    except KeyError:
        return pattern_id


def build_common_stumbling_blocks(db: Session, student_ids: list[str]) -> list[dict]:
    """按当前 active 会话聚合班级共性卡点；同一学生同一题阶段只计一次。"""
    if not student_ids:
        return []
    sessions = (db.query(TutorSession)
                .filter(TutorSession.student_id.in_(student_ids), TutorSession.status == "active")
                .all())
    grouped: dict[tuple[str, str], set[str]] = {}
    for session in sessions:
        if session.is_coop:
            continue
        grouped.setdefault((session.pattern_id, session.stage), set()).add(session.student_id)
    rows = [
        {
            "pattern_id": pattern_id,
            "pattern_name": _pattern_name(pattern_id),
            "stage": stage,
            "student_count": len(ids),
        }
        for (pattern_id, stage), ids in grouped.items()
    ]
    rows.sort(key=lambda row: (-row["student_count"], row["pattern_id"], row["stage"]))
    return rows[:8]


def _aggregate_teaching_metrics(db: Session, sessions: list[TutorSession]) -> dict:
    metrics = [process.teaching_metrics(db, session.id) for session in sessions]
    confusion = sum(m["confusion_turns"] for m in metrics)
    recovered = sum(m["recovered_within_two_turns"] for m in metrics)
    routes: dict[str, int] = {}
    for metric in metrics:
        for route, count in metric["routes"].items():
            routes[route] = routes.get(route, 0) + count
    return {
        "tutor_turns": sum(m["tutor_turns"] for m in metrics),
        "confusion_turns": confusion,
        "route_changed_turns": sum(m["route_changed_turns"] for m in metrics),
        "knowledge_gap_turns": sum(m["knowledge_gap_turns"] for m in metrics),
        "recovered_within_two_turns": recovered,
        "recovery_rate": round(recovered / confusion, 3) if confusion else None,
        "routes": routes,
    }


def build_student_detail(db: Session, student_id: str) -> dict | None:
    """教师钻取：学生进度、最近非 coop 会话和教学策略效果，全部由事实表派生。"""
    student = db.get(Student, student_id)
    if student is None:
        return None
    states = db.query(KnowledgeState).filter_by(student_id=student_id).all()
    all_sessions = (db.query(TutorSession).filter_by(student_id=student_id)
                    .order_by(TutorSession.updated_at.desc()).all())
    learning_sessions = [session for session in all_sessions if not session.is_coop]
    recent = []
    for session in learning_sessions[:10]:
        metric = process.teaching_metrics(db, session.id)
        recent.append({
            "session_id": session.id,
            "pattern_id": session.pattern_id,
            "pattern_name": _pattern_name(session.pattern_id),
            "stage": session.stage,
            "mine_status": session.mine_status,
            "status": session.status,
            "created_at": session.created_at,
            "updated_at": session.updated_at or session.created_at,
            "teaching_metrics": metric,
        })
    return {
        "student": {"student_id": student.id, "name": student.name, "class_id": student.class_id},
        "progress": {
            "solved": sum(1 for state in states if state.state in ("已解决", "已内化")),
            "internalized": sum(1 for state in states if state.state == "已内化"),
            "touched": sum(1 for state in states if state.state == "已接触"),
        },
        "current": _current_level(db, student_id),
        "teaching_metrics": _aggregate_teaching_metrics(db, learning_sessions),
        "sessions": recent,
    }


def build_class_overview(db: Session, class_id: str | None = None) -> dict:
    """全班总览（纯派生）。每人一行：进度 + 最近活跃 + 正在进行。按最近活跃倒序。"""
    q = db.query(Student)
    if class_id:
        q = q.filter_by(class_id=class_id)
    students = q.all()

    rows = []
    for s in students:
        ks = db.query(KnowledgeState).filter_by(student_id=s.id).all()
        solved = sum(1 for k in ks if k.state in ("已解决", "已内化"))   # 已内化也解决过
        internalized = sum(1 for k in ks if k.state == "已内化")
        touched = sum(1 for k in ks if k.state == "已接触")             # 在学未解决
        pres = presence.presence_signals(db, s.id)
        rows.append({
            "student_id": s.id,
            "name": s.name,
            "class_id": s.class_id,
            "solved": solved,
            "internalized": internalized,
            "touched": touched,
            "last_active_at": pres["last_active_at"],
            "days_since": pres["days_since"],
            "current": _current_level(db, s.id),
        })
    # 最近活跃倒序（无记录排最后）
    rows.sort(key=lambda r: r["last_active_at"] or "", reverse=True)
    return {
        "students": rows,
        "total": len(rows),
        "class_id": class_id,
        "common_stumbling_blocks": build_common_stumbling_blocks(
            db, [student.id for student in students],
        ),
    }
