"""教师端总览（M4）· 纯派生只读。

给老师一页看全班：每个学生做到哪、解决/内化几题、最近活跃、正卡在哪。
复用现有派生（knowledge_states / presence / active-session），零新表。
班级：class_id 现阶段多为空，传了就按班过滤，不传看全体。
"""

from sqlalchemy.orm import Session

from ..models import KnowledgeState, Student, TutorSession
from . import mine_engine, presence


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
        return {"pattern_name": name, "stage": s.stage}
    return None


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
    return {"students": rows, "total": len(rows), "class_id": class_id}
