"""统一续学决策（纯派生读模型）。

把未完成会话、到期复习和画像推荐收敛成一个可解释的下一步。它不写库、不改事件流；
训练大厅与成长页共同读取这里，避免各自在前端复制优先级。
"""

from sqlalchemy.orm import Session

from ..models import TutorSession
from . import mine_engine, profile, review

DECISION_ORDER = ["resume", "review", "recommend", "start"]


def active_session_summaries(db: Session, student_id: str, limit: int = 5) -> list[dict]:
    """最近活跃的非 coop 未完成会话；供决策与档案列表共用。"""
    sessions = (db.query(TutorSession)
                .filter_by(student_id=student_id, status="active")
                .order_by(TutorSession.updated_at.desc()).all())
    sessions = [session for session in sessions if not session.is_coop][:limit]
    out = []
    for session in sessions:
        try:
            name = mine_engine.get_pattern(session.pattern_id).get("name", session.pattern_id)
        except KeyError:
            name = session.pattern_id
        out.append({
            "session_id": session.id,
            "pattern_id": session.pattern_id,
            "name": name,
            "stage": session.stage,
            "mine_status": session.mine_status,
            "last_active_at": session.updated_at or session.created_at,
        })
    return out


def decide_next_action(active: list[dict], due: list[dict], recommendations: list[dict]) -> dict:
    """按固定优先级选一个行动，并把判断依据显式返回。"""
    if active:
        item = active[0]
        stage = (item.get("stage") or "①发现")[1:]
        action = {
            "kind": "resume",
            "title": f"继续想通“{item['name']}”",
            "detail": f"上次停在{stage}，先把已经开始的思路收完整。",
            "cta": "继续上次",
            "reason_code": "unfinished_first",
            "target": {"session_id": item["session_id"], "pattern_id": item["pattern_id"], "mode": "debug"},
            "evidence": {"type": "active_session", "ref": item["session_id"], "stage": item.get("stage")},
        }
    elif due:
        item = due[0]
        action = {
            "kind": "review",
            "title": f"再独立做一次“{item['name']}”",
            "detail": f"{item['days_since']} 天前学过，现在回看最容易变成长久记忆。",
            "cta": "开始复习",
            "reason_code": "spaced_review_due",
            "target": {"pattern_id": item["pattern_id"], "mode": "review"},
            "evidence": {"type": "review_due", "ref": item["pattern_id"],
                         "days_since": item["days_since"], "interval_days": item["interval_days"]},
        }
    elif recommendations:
        item = recommendations[0]
        action = {
            "kind": "recommend",
            "title": item["name"],
            "detail": item.get("reason") or "按你已经留下的学习证据，选择当前最值得练的一题。",
            "cta": "按推荐练习",
            "reason_code": "profile_recommendation",
            "target": {"pattern_id": item["id"], "mode": "debug"},
            "evidence": {"type": "profile_recommendation", "ref": item["id"],
                         "knowledge_points": item.get("knowledge_points") or []},
        }
    else:
        action = {
            "kind": "start",
            "title": "完成一次真实调试",
            "detail": "亲自运行、判断和修改，第一条成长证据就从这里开始。",
            "cta": "开始练习",
            "reason_code": "fresh_start",
            "target": {"pattern_id": None, "mode": "debug"},
            "evidence": {"type": "no_pending_work", "ref": None},
        }

    return {
        "action": action,
        "pending": {
            "active": len(active),
            "reviews": len(due),
            "recommendations": len(recommendations),
        },
        "decision_order": DECISION_ORDER,
    }


def build_next_action(db: Session, student_id: str) -> dict:
    """从现有派生数据生成统一下一步；任何消费者拿到的规则完全相同。"""
    active = active_session_summaries(db, student_id)
    due = review.due_queue(db, student_id)
    patterns = list(mine_engine.load_patterns().values())
    recommendations = profile.recommend_patterns(db, student_id, patterns)
    return decide_next_action(active, due, recommendations)
