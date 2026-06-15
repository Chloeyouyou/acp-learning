"""B1 · Debug Timeline（成长轨迹）。

纯派生只读视图：把 execution_events（尝试链）+ 观察卡（观察/猜测）+ Internalization/transfer
事件（收获）按「一道题 = 一个 Episode」串成可回看的调试故事。

铁律：绝不写库、不改事件流。整个文件是可替换的派生函数——将来换更聪明的叙事/聚类逻辑
只动这里，事件流 schema 不变（07 文档）。
"""

from collections import defaultdict

from sqlalchemy.orm import Session

from ..models import Event, ExecutionEvent, TutorSession
from . import mine_engine

OBSERVATION_MARK = "【观察记录】"

# 雷状态优劣排序，取一道题多次调试里的「最好结果」
_STATE_RANK = {"planted": 0, "found": 1, "fixed": 2, "internalized": 3}
_STATE_LABEL = {"planted": "进行中", "found": "进行中", "fixed": "已解决", "internalized": "已内化"}
_CAT_LABEL = {"boundary": "边界条件", "loop": "循环逻辑", "null": "空值 / None 处理"}

# 跨题思维默认值的 taxonomy（镜子，非审判）。name=给用户看的"默认值"，advice=做题前自问短句。
# 题→簇的归属在各 pattern YAML 的 thinking_pattern 字段；这里只存展示文案。
THINKING_PATTERNS = {
    "assume_valid": {"name": "默认输入和返回值总是正常、有效",
                     "advice": "如果它是空的、找不到、是 None 呢？"},
    "index_confusion": {"name": "下标和「个数 / 行列」容易搞混",
                        "advice": "n 个元素，下标只到 n−1，对吗？"},
    "loop_progress": {"name": "默认循环一定会推进、会停下",
                      "advice": "这个循环每一轮都在靠近终点吗？"},
    "crash_site": {"name": "盯着报错那一行，没往前追根",
                   "advice": "这个坏值，是从哪一步传进来的？"},
    "control_semantics": {"name": "控制流 / 层级的语义容易混",
                          "advice": "这一步是要跳过、退出、还是继续？"},
    "shared_state": {"name": "改了正在用、或被共享的东西",
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


def aggregate_thinking_patterns(episodes):
    """跨题认知模式聚合：从多段 Episode 提炼"反复出现的思维默认值"。纯派生、可整体替换。

    规则：按 pattern 的 thinking_pattern 归簇，计**不同题数**（惯性=跨题）；只留 ≥2 题的簇、
    按题数降序取前 3。count 只是证据数量，不是分数。未来要按"是否真挣扎/最近N次"加权、
    或换 embedding 聚类，只动这个函数。
    """
    groups = {}
    for ep in episodes:
        try:
            tp = mine_engine.get_pattern(ep["pattern_id"]).get("thinking_pattern")
        except KeyError:
            tp = None
        if tp:
            groups.setdefault(tp, [])
            if ep["pattern_name"] not in groups[tp]:
                groups[tp].append(ep["pattern_name"])
    items = []
    for tp_id, names in groups.items():
        if len(names) < 2:
            continue
        meta = THINKING_PATTERNS.get(tp_id, {"name": tp_id, "advice": ""})
        items.append({"id": tp_id, "name": meta["name"], "advice": meta["advice"],
                      "count": len(names), "members": names})
    items.sort(key=lambda x: x["count"], reverse=True)
    items = items[:3]
    if not items:
        return {"enough": False, "hint": "再多走几道题，这里会慢慢照出你常用的思维方式。"}
    return {"enough": True, "items": items}


def build_timeline(db: Session, student_id: str) -> dict:
    """返回 {"episodes": [...], "persona": {...}}。纯读，不写任何表。"""
    sessions = (db.query(TutorSession)
                .filter_by(student_id=student_id)
                .order_by(TutorSession.created_at.asc()).all())
    if not sessions:
        return {"episodes": [], "persona": _persona([]),
                "thinking_patterns": aggregate_thinking_patterns([])}

    sess_ids = [s.id for s in sessions]

    ex_by_sess = defaultdict(list)
    for e in (db.query(ExecutionEvent)
              .filter(ExecutionEvent.session_id.in_(sess_ids))
              .order_by(ExecutionEvent.timestamp.asc()).all()):
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

        # 观察/猜测：取最早一次有观察卡的 session 作故事起点
        observation = guess = None
        for s in sorted(plist, key=lambda x: x.created_at):
            observation, guess = _parse_observation(s.history)
            if observation or guess:
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
