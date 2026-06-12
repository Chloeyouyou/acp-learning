"""能力画像（05文档）。能力向量 + 知识点状态机 + 维度聚合。事件流是唯一事实源。"""

from sqlalchemy.orm import Session

from ..config import BASE_STEP, COLD_START_EVENTS, COLD_START_FACTOR, INITIAL_SCORE
from ..models import CapabilityScore, Event, KnowledgeState
from ..registry import CAPABILITY_REGISTRY


def apply_event(db: Session, event: Event):
    """score_new = clamp(score_old + delta × K, 0, 100)，K = 基础步长 × confidence × 冷启动系数。"""
    row = db.get(CapabilityScore, (event.student_id, event.capability))
    if row is None:
        row = CapabilityScore(
            student_id=event.student_id,
            capability=event.capability,
            score=INITIAL_SCORE,
            events_count=0,
        )
        db.add(row)

    cold = COLD_START_FACTOR if row.events_count < COLD_START_EVENTS else 1.0
    k = BASE_STEP * event.confidence * cold
    row.score = max(0.0, min(100.0, row.score + event.delta * k))
    row.events_count += 1
    row.last_event_at = event.timestamp


def update_knowledge_state(db: Session, *, student_id: str, pattern_id: str,
                           knowledge_points: list, new_state: str):
    """状态机：未接触→已接触→已解决→已内化。只前进不后退（回退由Internalization负事件驱动，V0.3）。"""
    order = ["未接触", "已接触", "已解决", "已内化"]
    row = db.get(KnowledgeState, (student_id, pattern_id))
    if row is None:
        # 列默认值在flush时才生效，构造时显式赋值避免读到None
        row = KnowledgeState(student_id=student_id, pattern_id=pattern_id,
                             knowledge_points=knowledge_points, state="未接触")
        db.add(row)
    if order.index(new_state) > order.index(row.state):
        row.state = new_state
    db.commit()


def get_profile(db: Session, student_id: str) -> dict:
    """四维画像（MVP：Debug能力 + AI协作能力两维，05文档 §9）。每个数字可下钻到事件。"""
    rows = db.query(CapabilityScore).filter_by(student_id=student_id).all()
    vector = {
        r.capability: {"score": round(r.score, 1), "events_count": r.events_count,
                       "confidence": "low" if r.events_count < 5 else "normal"}
        for r in rows
    }

    dimensions = []
    for dim in ["Debug能力", "AI协作能力"]:
        total_w, acc, n = 0.0, 0.0, 0
        for cap, meta in CAPABILITY_REGISTRY.items():
            if meta["dimension"] == dim and cap in vector:
                acc += vector[cap]["score"] * meta["weight"]
                total_w += meta["weight"]
                n += vector[cap]["events_count"]
        score = round(acc / total_w, 1) if total_w > 0 else None
        dimensions.append({"name": dim, "score": score,
                           "confidence": "low" if n < 5 else "normal"})

    states = db.query(KnowledgeState).filter_by(student_id=student_id).all()
    return {
        "student_id": student_id,
        "dimensions": dimensions,
        "vector": vector,
        "knowledge_states": [
            {"pattern_id": s.pattern_id, "knowledge_points": s.knowledge_points, "state": s.state}
            for s in states
        ],
    }


def get_capability_events(db: Session, student_id: str, capability: str) -> list[dict]:
    """下钻链路：能力 → 事件流 → evidence（05文档 §5.2）。"""
    rows = (db.query(Event)
            .filter_by(student_id=student_id, capability=capability)
            .order_by(Event.timestamp.desc()).all())
    return [
        {"event_id": r.event_id, "delta": r.delta, "producer": r.producer,
         "confidence": r.confidence, "evidence": r.evidence,
         "context": r.context, "timestamp": r.timestamp}
        for r in rows
    ]
