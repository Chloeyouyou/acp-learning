"""复习队列（间隔重复）。

纯派生只读视图（镜像 timeline.py 的哲学）：把「已解决/已内化的题」+「最近一次解决时间」
按精简 SM-2 间隔阶梯算出「今天该复习哪些」。

铁律：绝不写库、不新建表、不改事件流。复习本身复用现有 createSession(pattern_id, mode="review")
重开同一道题——新产生的 ExecutionEvent 自然把 last_solved_at 往后推、间隔升档，闭环自洽。
整个文件是可替换的派生函数：将来换更聪明的排程只动这里。
"""

from datetime import date, datetime

from sqlalchemy.orm import Session

from ..models import ExecutionEvent, KnowledgeState
from . import mine_engine

# 复习资格：到达这两个状态的题才进队列（未解决的还在正常闯关，不算复习）
_ELIGIBLE_STATES = {"已解决", "已内化"}

# 间隔阶梯（天）：复习轮次越高、间隔越长；已内化比已解决整体高一档。
# 按 round-1 取档，超出取末档。round = 历史上解决过几次（不同天数）。
_INTERVALS = {
    "已解决": [2, 4, 7, 15],
    "已内化": [4, 7, 15, 30],
}


def _day(ts: str) -> str:
    """ISO 时间戳取日期 YYYY-MM-DD。"""
    return (ts or "")[:10]


def _interval_for(state: str, round_n: int) -> int:
    """按状态 + 复习轮次取间隔天数。round_n≥1。"""
    ladder = _INTERVALS.get(state, _INTERVALS["已解决"])
    idx = min(max(round_n - 1, 0), len(ladder) - 1)
    return ladder[idx]


def _solved_days(executions) -> list[str]:
    """这道题历史上「解决成功」的不同天数（升序）。submit + OK 才算一次成功解决。"""
    days = {_day(e.timestamp) for e in executions
            if e.source == "submit" and e.kind == "OK"}
    return sorted(d for d in days if d)


def due_queue(db: Session, student_id: str, today: date | None = None) -> list[dict]:
    """返回该生今天到期/即将到期的复习题，按「逾期越久越靠前」排序。纯读、不写库。

    每项：{pattern_id, name, category, state, round, last_solved_at,
           days_since, interval_days, due}。
    """
    today = today or date.today()

    states = (db.query(KnowledgeState)
              .filter(KnowledgeState.student_id == student_id,
                      KnowledgeState.state.in_(_ELIGIBLE_STATES))
              .all())
    if not states:
        return []

    # 一次取全该生执行事实，按 pattern 分组（避免 N 次查询）
    pids = [s.pattern_id for s in states]
    execs = (db.query(ExecutionEvent)
             .filter(ExecutionEvent.student_id == student_id,
                     ExecutionEvent.pattern_id.in_(pids))
             .all())
    ex_by_pid: dict[str, list] = {}
    for e in execs:
        ex_by_pid.setdefault(e.pattern_id, []).append(e)

    items = []
    for ks in states:
        solved_days = _solved_days(ex_by_pid.get(ks.pattern_id, []))
        # 没有「submit/OK」执行事实兜底用知识状态更新时间（如老数据/迁移题）
        last_solved = solved_days[-1] if solved_days else _day(ks.updated_at)
        if not last_solved:
            continue
        round_n = len(solved_days) or 1
        interval = _interval_for(ks.state, round_n)
        try:
            last_d = datetime.strptime(last_solved, "%Y-%m-%d").date()
        except ValueError:
            continue
        days_since = (today - last_d).days
        try:
            pat = mine_engine.get_pattern(ks.pattern_id)
        except KeyError:
            pat = {}
        items.append({
            "pattern_id": ks.pattern_id,
            "name": pat.get("name", ks.pattern_id),
            "category": pat.get("category", ""),
            "state": ks.state,
            "round": round_n,
            "last_solved_at": last_solved,
            "days_since": days_since,
            "interval_days": interval,
            "due": days_since >= interval,
        })

    # 只返回到期的，逾期越久越靠前
    due = [it for it in items if it["due"]]
    due.sort(key=lambda it: it["days_since"] - it["interval_days"], reverse=True)
    return due


def pick_review_variant(pattern: dict) -> dict:
    """复习选题：有 variant_pool 时可换变式考迁移；MVP 先重放原题。

    预留接口——将来从 variant_pool 抽一道相似 bug 考查迁移能力，
    现在直接返回原题 id。
    """
    return {"pattern_id": pattern["id"], "is_variant": False}
