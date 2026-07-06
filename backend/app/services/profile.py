"""能力画像（05文档）。能力向量 + 知识点状态机 + 维度聚合。事件流是唯一事实源。"""

from sqlalchemy.orm import Session

from ..config import BASE_STEP, COLD_START_EVENTS, COLD_START_FACTOR, INITIAL_SCORE
from ..models import CapabilityScore, Event, ExecutionEvent, KnowledgeState, TutorSession
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
        full_w, acc, n, trained, total_caps = 0.0, 0.0, 0, 0, 0
        for cap, meta in CAPABILITY_REGISTRY.items():
            if meta["dimension"] != dim:
                continue
            total_caps += 1                         # 该维度的子能力总数
            full_w += meta["weight"]                # 全部子能力权重和（未练的也计入分母）
            if cap in vector:
                acc += vector[cap]["score"] * meta["weight"]
                n += vector[cap]["events_count"]
                trained += 1                        # 其中有证据（练过）的子能力数
        # #18 修法 A：维度分 = acc / 全部子能力权重和——**未练的子能力按 0 计入**。
        # 单练一项刷满不再把整维度顶到 100（只练独立调试→Debug=25），分数直接反映"全面不全面"，
        # 最诚实、不靠额外文字。trained/total 仍保留作覆盖度语境。有过任一证据才给分（否则 None）。
        score = round(acc / full_w, 1) if trained > 0 else None
        dimensions.append({"name": dim, "score": score,
                           "confidence": "low" if n < 5 else "normal",
                           "trained": trained, "total": total_caps})

    states = db.query(KnowledgeState).filter_by(student_id=student_id).all()
    mastery = knowledge_mastery(db, student_id)        # B0：知识点掌握度（纯画像）
    practice = recommend_practice(db, student_id, mastery)  # B0：推荐（独立策略函数）
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
        "knowledge_mastery": mastery,
        "practice": practice,
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


def knowledge_mastery(db: Session, student_id: str) -> list[dict]:
    """B0 派生视图（**只算画像/事实，不含推荐**，可替换的"计算器"）。
    Mastery=学会没有；Confidence=证据是否充足（按 evidence_count，与 struggle 解耦）。
    纯派生：读 knowledge_states + execution_events + 迁移事件，可重放，不存储掌握度。
    """
    from . import mine_engine

    states = db.query(KnowledgeState).filter_by(student_id=student_id).all()
    if not states:
        return []
    ex = db.query(ExecutionEvent).filter_by(student_id=student_id).all()

    # 迁移已验证的知识点：来自 Internalization 的 transfer 事件，取变式题的知识点
    transfer_kps: set[str] = set()
    for e in db.query(Event).filter_by(student_id=student_id, capability="Internalization").all():
        if (e.evidence or {}).get("type") == "transfer":
            vp = ((e.evidence or {}).get("refs") or {}).get("variant_pattern")
            try:
                transfer_kps.update(mine_engine.get_pattern(vp).get("knowledge_points", []) if vp else [])
            except KeyError:
                pass

    # kp -> 该生在含此 kp 的模式上的状态集合
    kp_states: dict[str, set[str]] = {}
    for s in states:
        for kp in (s.knowledge_points or []):
            kp_states.setdefault(kp, set()).add(s.state)

    order = {"生疏": 0, "在学": 1, "掌握": 2, "熟练": 3}
    out = []
    for kp, st in kp_states.items():
        # Mastery
        if "已内化" in st and kp in transfer_kps:
            mastery = "熟练"
        elif "已内化" in st:
            mastery = "掌握"
        elif "已解决" in st:
            mastery = "在学"
        else:
            mastery = "生疏"
        # 证据 / struggle（来自观测层执行日志）
        kp_ex = [e for e in ex if kp in (e.knowledge_points or [])]
        evidence_count = len(kp_ex)   # 真实执行次数（保持纯净，供 Timeline/遗忘曲线用）
        last_at = max((e.timestamp for e in kp_ex), default=None) \
            or max((s.updated_at for s in states if kp in (s.knowledge_points or [])), default=None)
        fails = sum(1 for e in kp_ex if e.source == "submit" and e.kind in ("RE", "WA", "HANG"))
        # Confidence=证据是否充足。已达成的状态本身就是强证据（避免"已掌握却证据0"的矛盾），
        # 与执行次数合并判定；仍不让失败影响（解耦保持）。
        state_evidence = (3 if "已内化" in st else 2 if "已解决" in st else 1 if "已接触" in st else 0)
        if kp in transfer_kps:
            state_evidence += 2
        basis = evidence_count + state_evidence
        confidence = "高" if basis > 8 else ("中" if basis >= 3 else "低")
        # weak / 理由
        weak, reason = False, ""
        if fails >= 2:
            weak, reason = True, "提交多次失败，建议再练"
        elif mastery == "生疏":
            weak, reason = True, "还没真正解决过"
        elif mastery == "在学":
            weak, reason = True, "已解决，建议内化巩固"
        out.append({"kp": kp, "mastery": mastery, "confidence": confidence,
                    "evidence_count": evidence_count, "last_practiced_at": last_at,
                    "weak": weak, "weak_reason": reason})
    # 薄弱排前：掌握档位升序，再按证据少在前
    out.sort(key=lambda x: (order[x["mastery"]], x["evidence_count"]))
    return out


def recommend_practice(db: Session, student_id: str, mastery_list: list[dict]) -> dict:
    """B0 推荐策略（**独立、可替换**，与画像计算解耦）。规则版：给薄弱 kp 各挑一道
    含该 kp 且未内化的题；并选一个「下一题推荐」。未来换知识图谱/数字孪生/RL 只改本函数。"""
    from . import mine_engine

    internalized = {
        s.pattern_id for s in db.query(KnowledgeState)
        .filter_by(student_id=student_id, state="已内化").all()
    }
    patterns = list(mine_engine.load_patterns().values())

    def pick_for_kp(kp: str) -> dict | None:
        for p in patterns:
            if kp in (p.get("knowledge_points") or []) and p["id"] not in internalized:
                return {"pattern_id": p["id"], "name": p["name"]}
        return None

    by_kp = {}
    for m in mastery_list:
        if m["weak"]:
            pick = pick_for_kp(m["kp"])
            if pick:
                by_kp[m["kp"]] = pick
    # 下一题 = 最薄弱（mastery_list 已排序）那个 kp 的练习
    nxt = None
    for m in mastery_list:
        if m["weak"] and m["kp"] in by_kp:
            nxt = {**by_kp[m["kp"]], "kp": m["kp"], "reason": m["weak_reason"]}
            break
    return {"next": nxt, "by_kp": by_kp}



def get_weakest_pattern_id(db: Session, student_id: str, patterns: list[dict]) -> str | None:
    """从所有 pattern 中，挑出学生最薄弱知识点的最佳练习题目。

    策略（01文档 §4 规则1+规则3）：
    1. 从未训练过的能力最优先（补弱）
    2. 已接触但未解决的次优先（推一把）
    3. 已解决但未内化的复习优先（间隔复现）
    4. 难度不超过最近发展区（L1-L2优先起步）
    """
    mastery = knowledge_mastery(db, student_id)

    # 构建 kp -> mastery 的快速查找
    kp_mastery = {m["kp"]: m for m in mastery}

    # 构建 pattern -> 评分
    scored = []
    for p in patterns:
        kps = p.get("knowledge_points", []) or []
        if not kps:
            continue

        # 该 pattern 下各 kp 的最差状态决定它的优先级
        worst = 4  # 4=熟练(好), 0=生疏(差)
        for kp in kps:
            m = kp_mastery.get(kp)
            if m is None:
                worst = 0  # 完全未接触 -> 最优先
            else:
                rank = {"熟练": 3, "掌握": 2, "在学": 1, "生疏": 0}
                r = rank.get(m["mastery"], 0)
                if r < worst:
                    worst = r

        # weak=True 意味着 kp 标记为薄弱
        has_weak = any(
            kp_mastery.get(kp, {}).get("weak", False)
            for kp in kps
        )

        # 难度加分：L1-L2 优先（最近发展区规则3）
        diff = p.get("difficulty", "L3")
        diff_rank = {"L1": 0, "L2": 1, "L3": 2, "L4": 3, "L5": 4}
        dr = diff_rank.get(diff, 2)

        # 总分：越薄弱越高分；有弱标记加分；难度越低加分
        # worst 越小=越薄弱，用 (4-worst) 反转让薄弱题得高分（修复原 score=worst*10 符号反了的 bug）
        score = (4 - worst) * 10 + (5 if has_weak else 0) - dr
        scored.append({"p": p, "score": score, "difficulty": dr})

    if not scored:
        return None

    # 按分数降序，同分按难度升序
    scored.sort(key=lambda x: (-x["score"], x["difficulty"]))
    # 规则4 防套路：不连续出同一道——若最高分正是上次刚做的题且有别的候选，换次优的
    last = (db.query(TutorSession.pattern_id).filter_by(student_id=student_id)
            .order_by(TutorSession.created_at.desc()).first())
    last_pid = last[0] if last else None
    if last_pid and scored[0]["p"]["id"] == last_pid and len(scored) > 1:
        return scored[1]["p"]["id"]
    return scored[0]["p"]["id"]


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
