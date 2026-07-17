"""B1 · Debug Timeline（成长轨迹）。

纯派生只读视图：把 execution_events（尝试链）+ 观察卡（观察/猜测）+ Internalization/transfer
事件（收获）按「一道题 = 一个 Episode」串成可回看的调试故事。

铁律：绝不写库、不改事件流。整个文件是可替换的派生函数——将来换更聪明的叙事/聚类逻辑
只动这里，事件流 schema 不变（07 文档）。
"""

import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import CodeSnapshot, Event, ExecutionEvent, SessionMessage, TutorSession
from . import learning_path, mine_engine, process

OBSERVATION_MARK = "【观察记录】"
SUMMARY_MARK = "【思考总结】"

# 雷状态优劣排序，取一道题多次调试里的「最好结果」
_STATE_RANK = {"planted": 0, "found": 1, "fixed": 2, "internalized": 3}
_STATE_LABEL = {"planted": "进行中", "found": "进行中", "fixed": "已解决", "internalized": "已内化"}
_CAT_LABEL = {"boundary": "边界条件", "loop": "循环逻辑", "null": "空值 / None 处理"}

# 跨题思维默认值的 taxonomy（镜子，非审判）。name=给用户看的"默认值"，advice=做题前自问短句。
# 题→簇的归属在各 pattern YAML 的 thinking_pattern 字段；这里只存展示文案。
THINKING_PATTERNS = {
    "assume_valid": {"name": "默认输入和返回值总是正常、有效",
                     "reminder": "默认输入和返回值一定是正常的",
                     "advice": "如果它是空的、找不到、是 None 呢？"},
    "index_confusion": {"name": "下标和「个数 / 行列」容易搞混",
                        "reminder": "把个数 / 长度当成了下标",
                        "advice": "n 个元素，下标只到 n−1，对吗？"},
    "loop_progress": {"name": "默认循环一定会推进、会停下",
                      "reminder": "默认循环一定会停下来",
                      "advice": "这个循环每一轮都在靠近终点吗？"},
    "crash_site": {"name": "盯着报错那一行，没往前追根",
                   "reminder": "只盯着报错那一行找原因",
                   "advice": "这个坏值，是从哪一步传进来的？"},
    "control_semantics": {"name": "控制流 / 层级的语义容易混",
                          "reminder": "把控制流或层级的语义弄混",
                          "advice": "这一步是要跳过、退出、还是继续？"},
    "shared_state": {"name": "改了正在用、或被共享的东西",
                     "reminder": "改动了正在用或被共享的东西",
                     "advice": "我动的这个，还有谁也在用它？"},
}


def _parse_observation(history):
    """从一个 session 的 history 取第一条观察卡，解析（观察, 猜测）。无则 (None, None)。"""
    for m in history or []:
        if m.get("role") != "user":
            continue
        content = m.get("content", "")
        if not content.startswith(OBSERVATION_MARK):
            continue
        if "暂时描述不出" in content:
            return "（当时没描述出来，请了导师一起看）", None
        obs = guess = None
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("我观察到："):
                obs = line[len("我观察到："):].strip() or None
            elif line.startswith("我的猜测："):
                guess = line[len("我的猜测："):].strip() or None
        return obs, guess
    return None, None


def _parse_summary(history):
    """从 session history 取学生主动留下的思考总结。无则返回 None。"""
    for m in reversed(history or []):
        if m.get("role") != "user":
            continue
        content = m.get("content", "")
        if not content.startswith(SUMMARY_MARK):
            continue
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("我想记住："):
                return line[len("我想记住："):].strip() or None
    return None


def _last_student_reflection(history):
    """已内化会话的自然对话兜底：最后一条有效学生回答就是他留下的总结。"""
    ignored = (OBSERVATION_MARK, SUMMARY_MARK, "（系统", "(系统", "📤")
    for m in reversed(history or []):
        if m.get("role") != "user":
            continue
        content = (m.get("content") or "").strip()
        if content and not content.startswith(ignored):
            return content[:300]
    return None


def _day(ts: str) -> str:
    """ISO 时间戳取日期 YYYY-MM-DD。"""
    return (ts or "")[:10]


def _observed_first(all_ex, observation) -> bool:
    """这道题学生是否「先观察再动手」：有观察卡，或第一次 submit 前先 run 过。"""
    if observation:
        return True
    seen_run = False
    for e in all_ex:
        if e.source == "run":
            seen_run = True
        elif e.source == "submit":
            return seen_run
    return seen_run


def _persona(items):
    """行为小脚注（观察习惯这一条轴）。镜子语气、不评分。items=[{observe_first}]（每题一项）。"""
    total = len(items)
    if total < 3:
        return {"enough": False}
    obs_n = sum(1 for i in items if i["observe_first"])
    if obs_n / total >= 0.6:
        line = f"另外，你越来越习惯先观察、再动手了（{obs_n}/{total} 次），这很好。"
    else:
        line = "另外，下次可以试试：先看清运行结果，再动手改——先观察往往更快。"
    return {"enough": True, "line": line}


def _recurring(episodes):
    """按 thinking_pattern 归簇、计**不同题数**（惯性=跨题），返回 {tp_id: [题名…]} 中 ≥2 的簇（不封顶）。
    聚合展示与开题干预的单一逻辑来源；未来换 embedding/加权聚类只动这里。"""
    groups = {}
    for ep in episodes:
        try:
            tp = mine_engine.get_pattern(ep["pattern_id"]).get("thinking_pattern")
        except KeyError:
            tp = None
        if not tp:
            continue
        groups.setdefault(tp, [])
        if ep["pattern_name"] not in groups[tp]:
            groups[tp].append(ep["pattern_name"])
    return {tp: names for tp, names in groups.items() if len(names) >= 2}


def aggregate_thinking_patterns(episodes):
    """跨题认知模式聚合「你最近常见的思维默认值」（Reflection）。

    题库 thinking_pattern 负责稳定归簇；学生的观察/猜测/总结作为这面镜子的个体证据。
    count 只作证据非分数。
    """
    rec = _recurring(episodes)
    items = []
    for tp_id, names in rec.items():
        meta = THINKING_PATTERNS.get(tp_id, {"name": tp_id, "advice": ""})
        reflections = []
        for ep in episodes:
            if ep["pattern_name"] not in names:
                continue
            note = ep.get("summary") or ep.get("guess") or ep.get("observation")
            if note and note not in reflections:
                reflections.append(note)
        items.append({"id": tp_id, "name": meta["name"], "advice": meta.get("advice", ""),
                      "count": len(names), "members": names,
                      "reflections": reflections[:2]})
    items.sort(key=lambda x: x["count"], reverse=True)
    items = items[:3]
    if not items:
        return {"enough": False, "hint": "再多走几道题，这里会慢慢照出你常用的思维方式。"}
    return {"enough": True, "items": items}


# 开题干预每次开题都要算跨题惯性，而 build_timeline 是全量 O(N) 重建。用按学生的短 TTL 缓存
# 挡掉重复重算（治体检 R4：一学期数据量后开题变慢）。惯性只随「碰到新思维簇的题」缓慢变化，
# 60s 内不会有意义地改变，故短 TTL 安全。进程内内存缓存，重启即清；GIL 护 dict 读写。
_RECURRING_CACHE: "dict[str, tuple[float, dict]]" = {}
_RECURRING_TTL = 60.0  # 秒


def recurring_for_student(db: Session, student_id: str) -> dict:
    """带短 TTL 缓存的 _recurring(build_timeline)。开题干预与聚合展示的单一读取入口。"""
    now = time.monotonic()
    hit = _RECURRING_CACHE.get(student_id)
    if hit and now - hit[0] < _RECURRING_TTL:
        return hit[1]
    rec = _recurring(build_timeline(db, student_id)["episodes"])
    _RECURRING_CACHE[student_id] = (now, rec)
    return rec


def clear_recurring_cache() -> None:
    """清空开题干预缓存（测试用；生产靠 TTL 自然过期）。"""
    _RECURRING_CACHE.clear()


def intervention_for(db: Session, student_id: str, pattern_id: str):
    """开题前干预（Intervention）：该题 thinking_pattern 若是用户跨题高频(≥2题)惯性，
    返回一句赋能提醒，否则 None。纯读、不写库。红线：赋能非评价、不打断。"""
    try:
        tp = mine_engine.get_pattern(pattern_id).get("thinking_pattern")
    except KeyError:
        tp = None
    if not tp:
        return None
    rec = recurring_for_student(db, student_id)   # 缓存版，避免每次开题全量重算 timeline
    if tp not in rec:
        return None
    meta = THINKING_PATTERNS.get(tp, {})
    return {"thinking_pattern": tp, "name": meta.get("name", ""),
            "reminder": meta.get("reminder", meta.get("name", "")),
            "advice": meta.get("advice", ""), "count": len(rec[tp])}


def debug_footprint(db: Session, student_id: str, episodes: list[dict], days: int = 7) -> dict:
    """「我的调试足迹」周报（方向一 1.3）：近 N 天过程数据的派生聚合，镜子非审判。

    练了几题/几次尝试/几天活跃、内化了什么、最常卡在哪一步（扶一把轮按四步语言聚合）、
    哪道题从试探走到定向、高频思维默认值是否松动。纯读不写库；episodes 复用
    build_timeline 已算好的结果，不重复重建。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    recent = [ep for ep in episodes if ep["last_at"] >= cutoff]
    attempts, day_set = 0, set()
    for ep in recent:
        for r in ep["rounds"]:
            hits = [a for a in r["attempts"] if a["time"] >= cutoff]
            attempts += len(hits)
            if hits:
                day_set.add(r["day"])
    if not attempts:
        return {"enough": False, "days": days}

    # 最常卡的一步：本周导师「扶一把」轮按 stage_before 聚合，翻成四步语言
    sess_ids = [s.id for s in db.query(TutorSession).filter_by(student_id=student_id).all()
                if not s.is_coop]
    stuck_counts: dict[str, int] = {}
    if sess_ids:
        support_msgs = (db.query(SessionMessage)
                        .filter(SessionMessage.session_id.in_(sess_ids),
                                SessionMessage.role == "tutor",
                                SessionMessage.created_at >= cutoff).all())
        for m in support_msgs:
            meta = m.meta or {}
            if meta.get("support_mode") and meta.get("stage_before"):
                step = learning_path.display_step(meta["stage_before"])
                stuck_counts[step] = stuck_counts.get(step, 0) + 1
    stuck_step = max(stuck_counts, key=stuck_counts.get) if stuck_counts else None

    # 从试探走到定向：本周解决/内化的题里，快照证据是「先在别处改、后来对准关键行」的
    progressed = []
    for ep in recent:
        if ep["outcome"] not in ("已解决", "已内化"):
            continue
        snaps = (db.query(CodeSnapshot).filter_by(session_id=ep["session_id"])
                 .order_by(CodeSnapshot.seq).all())
        if process.blind_start(snaps) is True:
            progressed.append(ep["pattern_name"])

    # 思维默认值松动：跨题高频簇里，本周有成员题走到已内化
    loosened = []
    for tp, names in _recurring(episodes).items():
        hit = next((ep for ep in recent
                    if ep["pattern_name"] in names and ep["outcome"] == "已内化"), None)
        if hit:
            meta = THINKING_PATTERNS.get(tp, {})
            loosened.append({"name": meta.get("name", tp), "pattern": hit["pattern_name"]})

    return {
        "enough": True, "days": days,
        "active_days": len(day_set), "attempts": attempts,
        "patterns_touched": len(recent),
        "internalized": [ep["pattern_name"] for ep in recent if ep["outcome"] == "已内化"],
        "solved": [ep["pattern_name"] for ep in recent if ep["outcome"] == "已解决"],
        "stuck_step": stuck_step,
        "stuck_count": stuck_counts.get(stuck_step, 0) if stuck_step else 0,
        "targeted_progress": progressed[:2],
        "loosened": loosened[:2],
    }


def build_timeline(db: Session, student_id: str) -> dict:
    """返回 {"episodes": [...], "persona": {...}}。纯读，不写任何表。"""
    sessions = (db.query(TutorSession)
                .filter_by(student_id=student_id)
                .order_by(TutorSession.created_at.asc()).all())
    # 防污染：AI 共脑调试（mode=coop）是独立玩法，不进成长轨迹（设计 09）。在此一处过滤，
    # 下游 executions/events 都按这批 session id 取，故 coop 的执行事件也一并排除。
    sessions = [s for s in sessions if not s.is_coop]
    if not sessions:
        return {"episodes": [], "persona": _persona([]),
                "thinking_patterns": aggregate_thinking_patterns([])}

    sess_ids = [s.id for s in sessions]

    all_executions = (db.query(ExecutionEvent)
                      .filter(ExecutionEvent.session_id.in_(sess_ids))
                      .order_by(ExecutionEvent.timestamp.asc()).all())
    ex_by_sess = defaultdict(list)
    for e in all_executions:
        ex_by_sess[e.session_id].append(e)

    ev_by_sess = defaultdict(list)
    for e in (db.query(Event)
              .filter(Event.session_id.in_(sess_ids))
              .order_by(Event.timestamp.asc()).all()):
        ev_by_sess[e.session_id].append(e)

    # 一道题 = 一个 Episode：按 pattern_id 聚合该生所有 session
    by_pattern = defaultdict(list)
    for s in sessions:
        by_pattern[s.pattern_id].append(s)

    episodes, persona_items = [], []
    for pid, plist in by_pattern.items():
        try:
            pat = mine_engine.get_pattern(pid)
        except KeyError:
            pat = {}

        all_ex = []
        for s in plist:
            all_ex.extend(ex_by_sess.get(s.id, []))
        all_ex.sort(key=lambda e: e.timestamp)

        # 观察/猜测取最早记录作故事起点；总结取最近一条，体现最后留下的经验。
        observation = guess = summary = None
        for s in sorted(plist, key=lambda x: x.created_at):
            observation, guess = _parse_observation(s.history)
            if observation or guess:
                break
        for s in sorted(plist, key=lambda x: x.created_at, reverse=True):
            summary = _parse_summary(s.history)
            if summary:
                break
        if not summary:
            for s in sorted(plist, key=lambda x: x.created_at, reverse=True):
                if s.mine_status == "internalized":
                    summary = _last_student_reflection(s.history)
                    if summary:
                        break

        # 过滤纯开没动的废会话
        if not all_ex and not observation:
            continue

        # 回合：按天分组，每天一条报错演变链
        rounds = []
        cur_day = None
        for e in all_ex:
            d = _day(e.timestamp)
            if d != cur_day:
                rounds.append({"day": d, "attempts": []})
                cur_day = d
            rounds[-1]["attempts"].append({
                "source": e.source, "kind": e.kind,
                "error_family": e.error_family, "time": e.timestamp})

        # 收获：内化/迁移事件的 summary
        gains = []
        for s in plist:
            for ev in ev_by_sess.get(s.id, []):
                etype = (ev.evidence or {}).get("type")
                if ev.capability == "Internalization" or etype == "transfer":
                    summary = (ev.evidence or {}).get("summary")
                    if summary:
                        gains.append(summary)

        best = max(plist, key=lambda s: _STATE_RANK.get(s.mine_status, 0))
        days = sorted({_day(e.timestamp) for e in all_ex})
        first_ts = all_ex[0].timestamp if all_ex else best.created_at
        last_ts = all_ex[-1].timestamp if all_ex else best.created_at

        episodes.append({
            "pattern_id": pid,
            "session_id": best.id,   # 回放入口：该题最有代表性的一局（状态最优）
            "pattern_name": pat.get("name", pid),
            "category": pat.get("category", ""),
            "cognitive_root": pat.get("cognitive_root", ""),
            "observation": observation,
            "guess": guess,
            "summary": summary,
            "rounds": rounds,
            "gains": gains,
            "outcome": _STATE_LABEL.get(best.mine_status, "进行中"),
            "session_count": len(plist),
            "day_count": len(days),
            "first_at": first_ts,
            "last_at": last_ts,
        })
        persona_items.append({"category": pat.get("category", ""),
                              "observe_first": _observed_first(all_ex, observation)})

    episodes.sort(key=lambda ep: ep["last_at"], reverse=True)
    return {"episodes": episodes, "persona": _persona(persona_items),
            "thinking_patterns": aggregate_thinking_patterns(episodes)}
