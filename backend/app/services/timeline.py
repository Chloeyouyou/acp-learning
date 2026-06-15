"""B1 · Debug Timeline（成长轨迹）。

纯派生只读视图：把 execution_events（尝试链）+ 观察卡（观察/猜测）+ Internalization/transfer
事件（收获）按「一道题 = 一个 Episode」串成可回看的调试故事。

铁律：绝不写库、不改事件流。整个文件是可替换的派生函数——将来换更聪明的叙事/聚类逻辑
只动这里，事件流 schema 不变（07 文档）。
"""

from collections import Counter, defaultdict

from sqlalchemy.orm import Session

from ..models import Event, ExecutionEvent, TutorSession
from . import mine_engine

OBSERVATION_MARK = "【观察记录】"

# 雷状态优劣排序，取一道题多次调试里的「最好结果」
_STATE_RANK = {"planted": 0, "found": 1, "fixed": 2, "internalized": 3}
_STATE_LABEL = {"planted": "进行中", "found": "进行中", "fixed": "已解决", "internalized": "已内化"}
_CAT_LABEL = {"boundary": "边界条件", "loop": "循环逻辑", "null": "空值 / None 处理"}


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
    """调试人格：纯统计、无评分无排行。items=[{category, observe_first}]（每题一项）。"""
    if len(items) < 3:
        return {"enough": False, "hint": "再多练几关，这里会长出你的「调试习惯画像」。"}
    total = len(items)
    cats = Counter(i["category"] for i in items if i["category"])
    lines = []
    if cats:
        top_cat, _ = cats.most_common(1)[0]
        lines.append(f"你在「{_CAT_LABEL.get(top_cat, top_cat)}」这类问题上练得最多——"
                     f"这是你正在重点打磨的地方，慢慢就摸透了。")
    obs_n = sum(1 for i in items if i["observe_first"])
    if obs_n / total >= 0.6:
        lines.append(f"你越来越习惯先观察、再动手了（{obs_n}/{total} 次）👍 这正是好调试者的样子。")
    else:
        lines.append("可以试着每次先看清运行结果、再下手改——先观察往往更快找到问题，"
                     "这个习惯会让你进步更快。")
    return {"enough": True, "lines": lines}


def build_timeline(db: Session, student_id: str) -> dict:
    """返回 {"episodes": [...], "persona": {...}}。纯读，不写任何表。"""
    sessions = (db.query(TutorSession)
                .filter_by(student_id=student_id)
                .order_by(TutorSession.created_at.asc()).all())
    if not sessions:
        return {"episodes": [], "persona": _persona([])}

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
    return {"episodes": episodes, "persona": _persona(persona_items)}
