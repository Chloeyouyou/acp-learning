"""课程/单元（M3b）。单元定义走静态 yaml（像题库），单元进度**纯从 knowledge_states 派生**——
零新表。改单元只动 curriculum.yaml；换更聪明的排程/解锁逻辑只动本文件。
"""

import yaml
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..models import KnowledgeState
from . import mine_engine, review

_CURRICULUM_FILE = BASE_DIR / "curriculum.yaml"
_units: list | None = None


def load_units() -> list[dict]:
    global _units
    if _units is None:
        data = yaml.safe_load(_CURRICULUM_FILE.read_text(encoding="utf-8"))
        _units = data.get("units", [])
    return _units


def build_curriculum(db: Session, student_id: str) -> dict:
    """课程地图（纯派生只读）：单元 → 关卡列表，每关带该生状态 + 复习到期标记，
    单元带进度汇总。全开放（不锁关），关卡顺序即推荐路径。"""
    units = load_units()
    states = {s.pattern_id: s.state for s in
              db.query(KnowledgeState).filter_by(student_id=student_id).all()}
    due = {d["pattern_id"] for d in review.due_queue(db, student_id)}

    out = []
    for u in units:
        levels, solved, internalized = [], 0, 0
        for pid in u.get("patterns", []):
            try:
                pat = mine_engine.get_pattern(pid)
                name, diff = pat.get("name", pid), pat.get("difficulty", "")
            except KeyError:
                name, diff = pid, ""      # 配置里写了但题库没有——不崩，原样带出
            st = states.get(pid, "未接触")
            if st == "已内化":
                internalized += 1
                solved += 1
            elif st == "已解决":
                solved += 1
            levels.append({"pattern_id": pid, "name": name, "difficulty": diff,
                           "state": st, "due": pid in due})
        out.append({
            "id": u["id"], "name": u["name"], "order": u.get("order", 0),
            "description": u.get("description", ""),
            "levels": levels, "total": len(levels),
            "solved": solved, "internalized": internalized,
        })
    out.sort(key=lambda x: x["order"])
    return {"units": out}
