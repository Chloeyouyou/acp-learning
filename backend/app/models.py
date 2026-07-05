from datetime import datetime, timezone

from sqlalchemy import JSON, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now():
    return datetime.now(timezone.utc).isoformat()


class Student(Base):
    """轻量身份（M1 D2-3）。学号即主键；无密码——token 由 HMAC 签发（见 security.py）。
    name/class_id 供显示与将来教师分班（M4）。首次 login 时 upsert。"""

    __tablename__ = "students"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")
    class_id: Mapped[str] = mapped_column(String, default="", index=True)
    created_at: Mapped[str] = mapped_column(String, default=now)


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
    # ③归因三步进度：variable_trace/rule_compare/root_cause_expression，未进③时为空
    attribution_step: Mapped[str] = mapped_column(String, default="")
    # ⑥内化三轴累计判定：{cause, locate, prevent} -> bool，≥2为通过
    internalize_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    history: Mapped[list] = mapped_column(JSON, default=list)  # [{role, content}]
    stalled_turns: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="active")  # active/completed
    created_at: Mapped[str] = mapped_column(String, default=now)
    # 最近活动时间：每次对话/运行/提交刷新。active-sessions 大厅按它排序，省去每会话回查 ExecutionEvent。
    # nullable（DB 层）：SQLite 无法给已有行的 NOT NULL 新列加约束；值始终由 default/touch 填，实际不为空。
    updated_at: Mapped[str | None] = mapped_column(String, default=now, index=True, nullable=True)

    def touch(self):
        """标记本会话刚有活动（更新 updated_at）。在任何会话状态变更处调用。"""
        self.updated_at = now()

    @property
    def is_coop(self) -> bool:
        """AI 共脑调试会话（mode=coop）——独立玩法，不进闯关大厅/成长轨迹/画像。"""
        return (self.manifest or {}).get("mode") == "coop"


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


class ExecutionEvent(Base):
    """观测层事实日志（路线B/06v2/07）。学生每次 run/submit 真跑代码的结果，一行一条。

    = Execution_Outcome 事件 + Debug Timeline（带时间戳）。是源数据、不是派生掌握度。
    **铁律：append-only——只 INSERT，永不 UPDATE/DELETE；未来修正用追加 Correction Event。**
    绝不影响 capability_scores（struggle 永不扣能力分）。
    """

    __tablename__ = "execution_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String, default="v1")  # 事件格式版本，未来升级不迁表
    student_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    pattern_id: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String)   # run / submit
    kind: Mapped[str] = mapped_column(String)     # RE / WA / HANG / OK
    error_family: Mapped[str | None] = mapped_column(String, nullable=True)  # IndexError/Timeout/WrongAnswer…
    knowledge_points: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # 预留：ontology_tags/trace_snapshot_id/std*_summary
    timestamp: Mapped[str] = mapped_column(String, default=now)


class CodeSnapshot(Base):
    """代码快照（M2 · 过程化核心）。学生每次 run/submit 时的代码原文，一行一条。

    这是「过程化」补上的最核心一块事实：事件流只记了每次执行的结果（RE/WA/OK），
    快照记下当时的**代码本身**——把「结果链」补成「代码链」，让解题过程可逐版回放、可做
    diff 分析（盲改 vs 定向改）。与 ExecutionEvent 一一对应（execution_event_id 关联）。
    **铁律：append-only——只 INSERT，永不 UPDATE/DELETE。**
    """

    __tablename__ = "code_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    execution_event_id: Mapped[str | None] = mapped_column(String, nullable=True)  # 关联的执行事实
    seq: Mapped[int] = mapped_column(Integer)   # 会话内第几次快照（1 起，回放步进用）
    code: Mapped[str] = mapped_column(Text)
    # 相对上一快照的变化：{lines_changed:int, touched_mine_line:bool|None}。touched_mine_line
    # 为 None 表示无从判断（coop 无 pattern，或首次快照）。
    diff_stats: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp: Mapped[str] = mapped_column(String, default=now)


class SessionMessage(Base):
    """会话消息时间线（M2 · 过程化回放）。会话里真实发生过的每一步对话/运行/提交，一行一条。

    与 `TutorSession.history`（LLM 工作副本，会删旧运行结果以免污染上下文）不同：本表是
    **append-only 的真实动作时间线**，保留发生过的每一步——回放（M3）据它 + code_snapshots
    按时间戳合并，还原「学生怎么一步步想通的」。
    当前为写新读旧过渡：写入此表，读取仍走 history；将来读取端迁完可移除 history 列。
    """

    __tablename__ = "session_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    seq: Mapped[int] = mapped_column(Integer)   # 会话内递增（同表稳定排序）
    role: Mapped[str] = mapped_column(String)   # student / tutor / system
    kind: Mapped[str] = mapped_column(String)   # chat / run_result / submit / tutor_opening
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, default=now)


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
