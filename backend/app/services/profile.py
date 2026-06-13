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
            {"pattern_id": s.pattern_id, "knowledge_points": s.knowledge_points, "state": s.state,
             # 已内化的知识点：若还有未内化的同类变式，挂上来供画像页「做变式巩固」
             "variant": pick_variant(db, student_id, s.pattern_id) if s.state == "已内化" else None}
            for s in states
        ],
    }


def _rec_item(p: dict, state: str, reason: str) -> dict:
    return {"id": p["id"], "name": p["name"], "category": p["category"],
            "difficulty": p["difficulty"], "knowledge_points": p.get("knowledge_points", []),
            "state": state, "reason": reason}


def recommend_patterns(db: Session, student_id: str, patterns: list[dict], limit: int = 3) -> list[dict]:
    """个性化推荐：基于能力向量（弱项优先）+ 知识点状态（已内化的不再推、已解决的转复习）。
    新手只给一道最基础的入门题；老手按「最能补强弱项」排序给若干。每条都带可读的推荐理由。"""
    prof = get_profile(db, student_id)
    states = {s["pattern_id"]: s["state"] for s in prof["knowledge_states"]}
    vector = prof["vector"]
    total_events = sum(v["events_count"] for v in vector.values())

    def cap_priority(cap: str) -> float:
        v = vector.get(cap)
        if not v or v["events_count"] == 0:
            return 100.0          # 从未训练过的能力，最该练
        return 100.0 - v["score"]  # 分数越低越该练

    # 学生已接触过的知识点（用于识别「全新领域」的题）
    seen_kps = set()
    for s in prof["knowledge_states"]:
        seen_kps.update(s.get("knowledge_points") or [])

    scored = []
    for p in patterns:
        state = states.get(p["id"], "未接触")
        if state == "已内化":
            continue              # 已掌握，不再推荐
        caps = p.get("capability_dims") or []
        target = max(caps, key=cap_priority) if caps else None
        value = sum(cap_priority(c) for c in caps) / len(caps) if caps else 0.0
        new_kps = [k for k in (p.get("knowledge_points") or []) if k not in seen_kps]
        scored.append({"p": p, "state": state, "value": value, "target": target,
                       "new_kps": new_kps})

    if not scored:
        return []

    # 新手（零事件）：只给一道最容易的入门题，避免一上来就被一堆选择压住
    if total_events == 0:
        p = min(scored, key=lambda x: x["p"]["difficulty"])["p"]
        return [_rec_item(p, "未接触", "新手起点 · 从最基础的一题开始，先熟悉闯关六步")]

    # 老手：贪心选出多样的几道——兼顾补强弱项、拓展新知识点、覆盖不同 Bug 类型，
    # 避免清一色「补强同一个能力」。每选一题就惩罚同类型/同弱项的后续候选。
    order = {"未接触": 0, "已接触": 1, "已解决": 2}
    picked_cats, picked_targets = set(), set()
    out = []
    while scored and len(out) < limit:
        def rank(s):
            div = (1 if s["p"]["category"] in picked_cats else 0) \
                + (1 if s["target"] in picked_targets else 0)
            kp_bonus = 12 if s["new_kps"] else 0  # 能拓展新知识点的题加权
            return (-(s["value"] + kp_bonus - div * 18), order.get(s["state"], 3), s["p"]["difficulty"])
        s = min(scored, key=rank)
        scored.remove(s)
        cap_zh = CAPABILITY_REGISTRY.get(s["target"], {}).get("zh") if s["target"] else None
        if s["state"] == "已解决":
            reason = f"复习巩固 · 再练一遍「{cap_zh}」" if cap_zh else "复习巩固"
        elif s["new_kps"]:
            reason = f"拓展新领域 · 「{'、'.join(s['new_kps'][:2])}」"
        elif cap_zh:
            reason = f"补强你较薄弱的「{cap_zh}」"
        else:
            reason = "推荐挑战"
        out.append(_rec_item(s["p"], s["state"], reason))
        picked_cats.add(s["p"]["category"])
        picked_targets.add(s["target"])
    return out


def pick_variant(db: Session, student_id: str, pattern_id: str) -> dict | None:
    """V0.3 迁移检验：从 pattern 的 variant_pool 里挑一道学生还没内化的变式题。
    同类异形的 Bug——能独立解出来才证明真的迁移会了，而不只是会背。"""
    from . import mine_engine
    try:
        pool = mine_engine.get_pattern(pattern_id).get("variant_pool") or []
    except KeyError:
        return None
    internalized = {
        s.pattern_id for s in db.query(KnowledgeState)
        .filter_by(student_id=student_id, state="已内化").all()
    }
    for vid in pool:
        if vid in internalized:
            continue
        try:
            vp = mine_engine.get_pattern(vid)
        except KeyError:
            continue
        return {"id": vid, "name": vp["name"], "category": vp["category"],
                "difficulty": vp["difficulty"]}
    return None


def transfer_source(db: Session, student_id: str, pattern_id: str) -> str | None:
    """若 pattern_id 是某个「学生已内化」题目的变式，返回那个源题 id——
    说明这是一次迁移检验（学生在相似 Bug 上的实战）。否则 None。"""
    from . import mine_engine
    internalized = {
        s.pattern_id for s in db.query(KnowledgeState)
        .filter_by(student_id=student_id, state="已内化").all()
    }
    for src in internalized:
        try:
            if pattern_id in (mine_engine.get_pattern(src).get("variant_pool") or []):
                return src
        except KeyError:
            continue
    return None


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
