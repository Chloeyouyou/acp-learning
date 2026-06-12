from datetime import datetime, timezone

from sqlalchemy import JSON, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now():
    return datetime.now(timezone.utc).isoformat()


class TutorSession(Base):
    """一次「学生×雷」的共脑调试会话。manifest 即 01 文档的 MineManifest。"""

    __tablename__ = "tutor_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    student_id: Mapped[str] = mapped_column(String, index=True)
    pattern_id: Mapped[str] = mapped_column(String)
    manifest: Mapped[dict] = mapped_column(JSON)
    stage: Mapped[str] = mapped_column(String, default="①发现")
    hint_level: Mapped[str] = mapped_column(String, default="L0")
    mine_status: Mapped[str] = mapped_column(String, default="planted")  # planted/found/fixed/internalized
    history: Mapped[list] = mapped_column(JSON, default=list)  # [{role, content}]
    stalled_turns: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="active")  # active/completed
    created_at: Mapped[str] = mapped_column(String, default=now)


class Event(Base):
    """能力事件（04文档 §3）。append-only，唯一事实源。"""

    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    student_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[str] = mapped_column(String, default=now)
    capability: Mapped[str] = mapped_column(String, index=True)
    delta: Mapped[int] = mapped_column(Integer)
    polarity: Mapped[str] = mapped_column(String)
    producer: Mapped[str] = mapped_column(String)  # rule / llm_judge
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[dict] = mapped_column(JSON)
    context: Mapped[dict] = mapped_column(JSON, default=dict)


class CapabilityScore(Base):
    """派生视图：能力向量（05文档 §2.2）。可由事件流重放重算。"""

    __tablename__ = "capability_scores"

    student_id: Mapped[str] = mapped_column(String, primary_key=True)
    capability: Mapped[str] = mapped_column(String, primary_key=True)
    score: Mapped[float] = mapped_column(Float)
    events_count: Mapped[int] = mapped_column(Integer, default=0)
    last_event_at: Mapped[str] = mapped_column(String, default=now)


class KnowledgeState(Base):
    """派生视图：知识点×模式状态机（05文档 §2.3）。"""

    __tablename__ = "knowledge_states"

    student_id: Mapped[str] = mapped_column(String, primary_key=True)
    pattern_id: Mapped[str] = mapped_column(String, primary_key=True)
    knowledge_points: Mapped[list] = mapped_column(JSON, default=list)
    state: Mapped[str] = mapped_column(String, default="未接触")  # 未接触/已接触/已解决/已内化
    updated_at: Mapped[str] = mapped_column(String, default=now)
    notes: Mapped[str] = mapped_column(Text, default="")
