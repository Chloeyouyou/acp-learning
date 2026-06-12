"""能力事件引擎（04文档）。双生产者（rule / llm_judge）→ 校验 → append-only入库 → 画像聚合。"""

import uuid

from sqlalchemy.orm import Session

from ..config import CONFIDENCE_THRESHOLD
from ..models import Event
from ..registry import CAPABILITY_REGISTRY, DELTA_MAX, DELTA_MIN, LLM_ALLOWED_CAPABILITIES
from . import profile


class EventRejected(ValueError):
    pass


def emit(
    db: Session,
    *,
    student_id: str,
    session_id: str,
    capability: str,
    delta: int,
    producer: str,
    evidence: dict,
    context: dict | None = None,
    confidence: float = 1.0,
) -> Event:
    """事件入库的唯一入口。校验失败抛 EventRejected，不落库。"""
    if capability not in CAPABILITY_REGISTRY:
        raise EventRejected(f"未注册的能力类型: {capability}")
    if producer == "llm_judge" and capability not in LLM_ALLOWED_CAPABILITIES:
        raise EventRejected(f"LLM不允许产出该类型事件: {capability}")
    if not (DELTA_MIN <= delta <= DELTA_MAX) or delta == 0:
        raise EventRejected(f"delta超出范围或为0: {delta}")
    if not evidence or not evidence.get("summary"):
        raise EventRejected("事件必须携带evidence.summary")
    if producer == "rule":
        confidence = 1.0

    event = Event(
        event_id=f"evt_{uuid.uuid4().hex[:16]}",
        student_id=student_id,
        session_id=session_id,
        capability=capability,
        delta=delta,
        polarity="positive" if delta > 0 else "negative",
        producer=producer,
        confidence=confidence,
        evidence=evidence,
        context=context or {},
    )
    db.add(event)

    # 低置信度LLM事件入库但不参与画像（04文档 §2.2）
    if confidence >= CONFIDENCE_THRESHOLD:
        profile.apply_event(db, event)
    db.commit()
    return event


# ---- 规则事件生产器（04文档 §2.1：确定性事件，不经过LLM）----

HINT_DELTA = {"L0": 3, "L1": 3, "L2": 2, "L3": 1}  # L4/L5 不计正分


def on_mine_fixed(db: Session, *, student_id: str, session_id: str, mine: dict, max_hint_level: str):
    """雷 found→fixed 结算：Independent_Debug 按全程最高提示级别定档（04文档 §4.4）。"""
    delta = HINT_DELTA.get(max_hint_level, 0)
    if delta == 0:
        return None
    return emit(
        db,
        student_id=student_id,
        session_id=session_id,
        capability="Independent_Debug",
        delta=delta,
        producer="rule",
        evidence={
            "type": "mine_transition",
            "summary": f"在≤{max_hint_level}提示下完成修复（{mine['pattern_id']}）",
            "refs": {"mine_id": mine["mine_id"], "pattern_id": mine["pattern_id"]},
        },
        context={"hint_level": max_hint_level, "knowledge_points": mine["knowledge_points"]},
    )


def on_boundary_located(db: Session, *, student_id: str, session_id: str, mine: dict, hint_level: str):
    """boundary类雷定位成功：Boundary_Awareness 按提示级别衰减（04文档 §4.2）。"""
    delta = {"L0": 2, "L1": 2, "L2": 1, "L3": 1}.get(hint_level, 0)
    if delta == 0:
        return None
    return emit(
        db,
        student_id=student_id,
        session_id=session_id,
        capability="Boundary_Awareness",
        delta=delta,
        producer="rule",
        evidence={
            "type": "mine_transition",
            "summary": f"在{hint_level}提示下定位边界类雷（{mine['pattern_id']}）",
            "refs": {"mine_id": mine["mine_id"], "pattern_id": mine["pattern_id"]},
        },
        context={"hint_level": hint_level, "knowledge_points": mine["knowledge_points"]},
    )


def on_answer_begging(db: Session, *, student_id: str, session_id: str, mine: dict):
    """学生索要答案被拒后再次索要：Independent_Debug -1（04文档 §4.4 负向事件）。"""
    return emit(
        db,
        student_id=student_id,
        session_id=session_id,
        capability="Independent_Debug",
        delta=-1,
        producer="rule",
        evidence={
            "type": "behavior_counter",
            "summary": "索要答案被拒后再次索要",
            "refs": {"mine_id": mine["mine_id"]},
        },
    )
