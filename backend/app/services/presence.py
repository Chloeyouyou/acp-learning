"""灵犀感知层（Presence Layer，设计 11）· 后端只读派生。

读人不追问：只消费 ACP 内已有的第一方信号，输出供大厅「读过你」招呼用的数据。
不建表、不动知返、不做情绪诊断。镜像 timeline/profile/review 的纯派生哲学。

第一版只提供「最近活跃时间」——补全大厅招呼里"久别回来/新朋友"这块
（现有前端 presenceHint 只覆盖"有未完成关卡"的情况）。
"""

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import ExecutionEvent, TutorSession


def presence_signals(db: Session, student_id: str) -> dict:
    """该生最近一次活动时间（ExecutionEvent 或 TutorSession 取更晚者）。
    返回 has_history（来过没）/ last_active_at / days_since（距今天数）。"""
    ex = db.query(func.max(ExecutionEvent.timestamp)).filter_by(student_id=student_id).scalar()
    se = db.query(func.max(TutorSession.created_at)).filter_by(student_id=student_id).scalar()
    stamps = [t for t in (ex, se) if t]
    if not stamps:
        return {"has_history": False, "last_active_at": None, "days_since": None}
    last = max(stamps)  # ISO 字符串、同格式同时区，可直接字典序比较
    days = None
    try:
        days = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).days
    except (ValueError, TypeError):
        pass
    return {"has_history": True, "last_active_at": last, "days_since": days}
