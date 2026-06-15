"""B1 · Debug Timeline（成长轨迹）。

纯派生只读视图：把 execution_events（尝试链）+ 观察卡（观察/猜测）+ Internalization/transfer
事件（收获）按「一道题 = 一个 Episode」串成可回看的调试故事。

铁律：绝不写库、不改事件流。整个文件是可替换的派生函数——将来换更聪明的叙事/聚类逻辑
只动这里，事件流 schema 不变（07 文档）。
"""

from collections import defaultdict

from sqlalchemy.orm import Session

from ..models import Event, ExecutionEvent, TutorSession
from . import bug_classifier, mine_engine

OBSERVATION_MARK = "【观察记录】"
SUMMARY_MARK = "【思考总结】"

# 雷状态优劣排序，取一道题多次调试里的「最好结果」
_STATE_RANK = {"planted": 0, "found": 1, "fixed": 2, "internalized": 3}
_STATE_LABEL = {"planted": "进行中", "found": "进行中", "fixed": "已解决", "internalized": "已内化"}
_CAT_LABEL = {"boundary": "边界条件", "loop": "循环逻辑", "null": "空值 / None 处理"}
_BUG_STATUS_RANK = {"observed": 0, "fixing": 1, "solved": 2, "internalized": 3}

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


def aggregate_bug_patterns(executions, sessions):
    """从执行事实聚合 Bug 类型概览。纯读，兼容尚未写入分类 meta 的旧事件。"""
    pattern_state = {}
    for session in sessions:
        current = pattern_state.get(session.pattern_id, "planted")
        if _STATE_RANK.get(session.mine_status, 0) > _STATE_RANK.get(current, 0):
            pattern_state[session.pattern_id] = session.mine_status

    groups = {}
    for execution in executions:
        if not execution.error_family:
            continue
        meta = execution.meta or {}
        classified = {
            "bug_type": meta.get("bug_type"),
            "concept_tags": meta.get("concept_tags") or meta.get("ontology_tags") or [],
            "confidence": meta.get("classification_confidence"),
        }
        if not classified["bug_type"]:
            classified = bug_classifier.classify_bug(
                error_family=execution.error_family,
                pattern_id=execution.pattern_id,
                knowledge_points=execution.knowledge_points,
            )

        bug_type = classified["bug_type"]
        if not bug_type or bug_type == "未知错误":
            continue

        mine_status = pattern_state.get(execution.pattern_id, "planted")
        if mine_status == "internalized":
            status = "internalized"
        elif mine_status == "fixed":
            status = "solved"
        elif execution.source == "submit":
            status = "fixing"
        else:
            status = "observed"

        item = groups.setdefault(bug_type, {
            "bug_type": bug_type,
            "concept_tags": [],
            "count": 0,
            "first_at": execution.timestamp,
            "last_at": execution.timestamp,
            "status": status,
            "pattern_ids": [],
        })
        item["count"] += 1
        item["first_at"] = min(item["first_at"], execution.timestamp)
        item["last_at"] = max(item["last_at"], execution.timestamp)
        if _BUG_STATUS_RANK[status] > _BUG_STATUS_RANK[item["status"]]:
            item["status"] = status
        for tag in classified["concept_tags"]:
            if tag not in item["concept_tags"]:
                item["concept_tags"].append(tag)
        if execution.pattern_id not in item["pattern_ids"]:
            item["pattern_ids"].append(execution.pattern_id)

    return sorted(groups.values(), key=lambda item: item["last_at"], reverse=True)


def intervention_for(db: Session, student_id: str, pattern_id: str):
    """开题前干预（Intervention）：该题 thinking_pattern 若是用户跨题高频(≥2题)惯性，
    返回一句赋能提醒，否则 None。纯读、不写库。红线：赋能非评价、不打断。"""
    try:
        tp = mine_engine.get_pattern(pattern_id).get("thinking_pattern")
    except KeyError:
        tp = None
    if not tp:
        return None
    rec = _recurring(build_timeline(db, student_id)["episodes"])
    if tp not in rec:
        return None
    meta = THINKING_PATTERNS.get(tp, {})
    return {"thinking_pattern": tp, "name": meta.get("name", ""),
            "reminder": meta.get("reminder", meta.get("name", "")),
            "advice": meta.get("advice", ""), "count": len(rec[tp])}


def build_timeline(db: Session, student_id: str) -> dict:
    """返回 {"episodes": [...], "persona": {...}}。纯读，不写任何表。"""
    sessions = (db.query(TutorSession)
                .filter_by(student_id=student_id)
                .order_by(TutorSession.created_at.asc()).all())
    if not sessions:
        return {"episodes": [], "persona": _persona([]),
                "thinking_patterns": aggregate_thinking_patterns([]),
                "bug_patterns": []}

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
            "thinking_patterns": aggregate_thinking_patterns(episodes),
            "bug_patterns": aggregate_bug_patterns(all_executions, sessions)}
