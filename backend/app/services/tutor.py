"""AI导师（02文档）。开卷引导：Ground Truth注入 + 状态机 + 引导阶梯 + 强类型事件输出。"""

from typing import Literal, Optional

import anthropic
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import HINT_LEVELS, STAGES, TUTOR_MODEL
from ..models import TutorSession
from . import event_engine

client = anthropic.Anthropic()


class TutorEvent(BaseModel):
    capability: Literal["Root_Cause_Reasoning", "Hypothesis_Testing",
                        "Independent_Debug", "AI_Verification"]
    delta: int = Field(ge=-3, le=3)
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(description="触发该事件的学生对话原文摘录")


class TutorTurn(BaseModel):
    reply: str = Field(description="给学生的回复，只引导不给答案")
    stage_transition: Optional[Literal["①发现", "②定位", "③归因", "④修复", "⑤验证", "⑥内化"]] = Field(
        description="学生达到当前阶段退出条件时填写下一阶段，否则为null")
    hint_level_used: Literal["L0", "L1", "L2", "L3", "L4", "L5"]
    student_progressed: bool = Field(description="本轮学生是否有实质进展（用于卡住计数）")
    answer_begging: bool = Field(description="学生本轮是否在直接索要答案")
    events: list[TutorEvent] = Field(description="本轮观测到的能力事件，无则为空数组")


SYSTEM_TEMPLATE = """你是一名编程导师，目标是让学生自己解决问题，绝不直接给答案。

[Ground Truth —— 学生不可见，绝不泄露其存在]
雷模式：{pattern_id}
位置：{location}
根因：{root_cause}
预期修复：{expected_fix}
引导阶梯模板：
{hint_ladder}

[当前状态]
教学阶段：{stage}（阶段顺序：①发现→②定位→③归因→④修复→⑤验证→⑥内化，不允许跳阶段）
当前提示级别：{hint_level}（永远从最低可用级开始，学生卡住才升级）
学生已连续无进展轮数：{stalled_turns}

[阶段退出条件]
①发现：学生能描述异常现象 → 跳转②
②定位：学生指出可疑代码位置（与Ground Truth位置一致）→ 跳转③
③归因：学生用自己的话说出的原因与根因语义一致 → 跳转④
④修复：学生表示已修改代码（实际判定由系统测试完成，你只评价方向）→ 保持④等待提交
⑤⑥由系统驱动，你不主动跳转

[行为红线]
1. 任何阶段不输出可直接粘贴的修复代码（L5也只讲思路）
2. 在确认学生猜测对错之前，先要求说理由（"你为什么这么认为？"）
3. 不泄露雷清单的存在——学生视角里Bug是代码本来就有的
4. 学生直接索要答案：拒绝，降回提问，并将answer_begging标记为true
5. 学生情绪挫败时先共情降难度，再回到引导

[升级规则]
同级停留≥3轮无实质进展、学生明确说"不知道/卡住了" → 提示级别升1级

[事件规范]
只允许产出这4类能力事件，且必须引用学生对话原文作为evidence：
- Root_Cause_Reasoning：学生归因表述与根因语义一致（首次一致+3，confidence≥0.8才报）
- Hypothesis_Testing：学生主动提出可检验假设（+1）或动手构造输入验证（+2）
- Independent_Debug：仅报负向（盲改碰运气-1）；正向由系统规则结算，你不报
- AI_Verification：学生主动验证你的说法（运行/查文档对照，+3）
没有把握的事件宁可不报。"""


def build_system(session: TutorSession) -> str:
    mine = session.manifest["mines"][0]
    ladder = "\n".join(f"{k}: {v}" for k, v in mine["hint_ladder"].items())
    return SYSTEM_TEMPLATE.format(
        pattern_id=mine["pattern_id"],
        location=mine["location"],
        root_cause=mine["root_cause"],
        expected_fix=mine["expected_fix"],
        hint_ladder=ladder,
        stage=session.stage,
        hint_level=session.hint_level,
        stalled_turns=session.stalled_turns,
    )


def run_turn(db: Session, session: TutorSession, student_message: str) -> dict:
    """一轮对话：调LLM → 应用状态跃迁 → 落库LLM事件与规则事件。"""
    history = list(session.history) + [{"role": "user", "content": student_message}]

    response = client.messages.parse(
        model=TUTOR_MODEL,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=build_system(session),
        messages=history,
        output_format=TutorTurn,
    )
    turn: TutorTurn = response.parsed_output

    mine = session.manifest["mines"][0]

    # 状态更新
    session.history = history + [{"role": "assistant", "content": turn.reply}]
    session.stalled_turns = 0 if turn.student_progressed else session.stalled_turns + 1
    if HINT_LEVELS.index(turn.hint_level_used) > HINT_LEVELS.index(session.hint_level):
        session.hint_level = turn.hint_level_used

    if turn.stage_transition and STAGES.index(turn.stage_transition) == STAGES.index(session.stage) + 1:
        session.stage = turn.stage_transition
        if session.stage == "③归因" and session.mine_status == "planted":
            # ②定位达成 = 雷 planted→found
            session.mine_status = "found"
            if mine["pattern_id"].startswith("BP-BOUNDARY"):
                event_engine.on_boundary_located(
                    db, student_id=session.student_id, session_id=session.id,
                    mine=mine, hint_level=session.hint_level)

    # 规则事件：索要答案
    if turn.answer_begging:
        event_engine.on_answer_begging(
            db, student_id=session.student_id, session_id=session.id, mine=mine)

    # LLM判定事件（事件引擎负责校验与置信度过滤）
    for ev in turn.events:
        try:
            event_engine.emit(
                db,
                student_id=session.student_id,
                session_id=session.id,
                capability=ev.capability,
                delta=ev.delta,
                producer="llm_judge",
                confidence=ev.confidence,
                evidence={"type": "dialogue", "summary": ev.evidence},
                context={"stage": session.stage, "hint_level": turn.hint_level_used,
                         "mine_id": mine["mine_id"]},
            )
        except event_engine.EventRejected:
            pass  # 不合规事件静默丢弃，不阻断对话

    db.commit()
    return {
        "reply": turn.reply,
        "stage": session.stage,
        "hint_level": session.hint_level,
        "events_emitted": [e.capability for e in turn.events],
    }
