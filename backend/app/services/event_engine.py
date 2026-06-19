"""能力事件引擎（04文档）。双生产者（rule / llm_judge）→ 校验 → append-only入库 → 画像聚合。"""

import re
import uuid

from sqlalchemy.orm import Session

from ..config import CONFIDENCE_THRESHOLD
from ..models import Event, ExecutionEvent, now
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

    # 列默认值flush才生效，而apply_event在flush前就要读timestamp，必须构造时显式赋值
    event = Event(
        event_id=f"evt_{uuid.uuid4().hex[:16]}",
        student_id=student_id,
        session_id=session_id,
        timestamp=now(),
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


# ---- 观测层：执行事实日志（路线B/B0）。append-only，绝不影响 capability_scores ----

# 从真实 stderr 末行解析异常类名（IndexError/TypeError/KeyError…）；非异常类的归一处理
def _error_family(kind: str, stderr: str) -> str | None:
    if kind == "HANG":
        return "Timeout"
    if kind == "WA":
        return "WrongAnswer"
    if kind == "OK":
        return None
    # RE：从 traceback 抓最后一行的异常类型，如 "IndexError: list index out of range"
    for line in reversed((stderr or "").strip().splitlines()):
        m = re.match(r"^([A-Za-z_][\w.]*Error|[A-Za-z_]\w*(?:Exception|Warning))\b", line.strip())
        if m:
            return m.group(1).split(".")[-1]
    return "RuntimeError"


def log_execution(db: Session, *, student_id: str, session_id: str, pattern_id: str,
                  source: str, kind: str, stderr: str = "", knowledge_points: list | None = None,
                  mode: str = "debug"):
    """记一条执行事实（run/submit 的真跑结果）。只 INSERT，不碰 capability_scores。

    mode 标记本次执行属于哪种玩法（debug/review/…），盖进 meta 供日后按玩法切片。
    """
    ev = ExecutionEvent(
        id=f"ex_{uuid.uuid4().hex[:16]}",
        version="v1",
        student_id=student_id,
        session_id=session_id,
        pattern_id=pattern_id,
        source=source,
        kind=kind,
        error_family=_error_family(kind, stderr),
        knowledge_points=knowledge_points or [],
        # meta 预留默认形状 + mode 盖戳
        meta={"ontology_tags": [], "trace_snapshot_id": None,
              "stderr_summary": None, "stdout_summary": None, "mode": mode},
        timestamp=now(),
    )
    db.add(ev)
    db.commit()
    return ev


# ---- 规则事件生产器（04文档 §2.1：确定性事件，不经过LLM）----

# 评分理念（用户确认）：用提示不扣分——这是学习工具不是考试。完成即给固定正分，
# 提示级别只记入 context 供洞察/将来做"强化信号"，不影响得分。
FIX_DELTA = 3
LOCATE_DELTA = 2


def on_mine_fixed(db: Session, *, student_id: str, session_id: str, mine: dict, max_hint_level: str):
    """雷 found→fixed 结算：Independent_Debug +固定分。用了多少提示不扣分（只记录）。"""
    return emit(
        db,
        student_id=student_id,
        session_id=session_id,
        capability="Independent_Debug",
        delta=FIX_DELTA,
        producer="rule",
        evidence={
            "type": "mine_transition",
            "summary": f"完成修复（{mine['pattern_id']}）",
            "refs": {"mine_id": mine["mine_id"], "pattern_id": mine["pattern_id"]},
        },
        context={"hint_level": max_hint_level, "knowledge_points": mine["knowledge_points"]},
    )


def on_boundary_located(db: Session, *, student_id: str, session_id: str, mine: dict, hint_level: str):
    """boundary类雷定位成功：Boundary_Awareness +固定分。用了多少提示不扣分（只记录）。"""
    return emit(
        db,
        student_id=student_id,
        session_id=session_id,
        capability="Boundary_Awareness",
        delta=LOCATE_DELTA,
        producer="rule",
        evidence={
            "type": "mine_transition",
            "summary": f"定位边界类雷（{mine['pattern_id']}）",
            "refs": {"mine_id": mine["mine_id"], "pattern_id": mine["pattern_id"]},
        },
        context={"hint_level": hint_level, "knowledge_points": mine["knowledge_points"]},
    )


def on_internalized(db: Session, *, student_id: str, session_id: str, mine: dict, axes: dict):
    """雷 fixed→internalized 结算：复述判定（成因/定位/迁移≥2轴）通过。
    Internalization 不在 LLM 白名单内——三轴判定虽由 LLM 报告，结算事件始终是规则产出。"""
    passed = [k for k, v in axes.items() if v]
    return emit(
        db,
        student_id=student_id,
        session_id=session_id,
        capability="Internalization",
        delta=3,
        producer="rule",
        evidence={
            "type": "mine_transition",
            "summary": f"复述判定通过（{len(passed)}/3轴：{'、'.join(passed)}），"
                       f"知识点已内化（{mine['pattern_id']}）",
            "refs": {"mine_id": mine["mine_id"], "pattern_id": mine["pattern_id"]},
        },
        context={"axes": axes, "knowledge_points": mine["knowledge_points"]},
    )


def on_transfer_confirmed(db: Session, *, student_id: str, session_id: str,
                          mine: dict, source_pattern: str, hint_level: str):
    """V0.3 迁移检验：学生在「已内化」题目的变式上独立解决（低提示）→ Internalization +2。
    这是比复述更硬的内化证据——把学到的道理用到了新的、相似的问题上。"""
    return emit(
        db,
        student_id=student_id,
        session_id=session_id,
        capability="Internalization",
        delta=2,
        producer="rule",
        evidence={
            "type": "transfer",
            "summary": f"迁移已验证：在 {source_pattern} 的变式（{mine['pattern_id']}）上"
                       f"以≤{hint_level}提示独立解决",
            "refs": {"mine_id": mine["mine_id"], "source_pattern": source_pattern,
                     "variant_pattern": mine["pattern_id"]},
        },
        context={"hint_level": hint_level, "source_pattern": source_pattern},
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
