"""ACP Learning 后端 MVP。

闭环：埋雷（创建会话）→ AI共脑对话 → 提交修复（规则判定）→ 事件 → 画像。
"""

import uuid

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .config import STAGES
from .db import get_db, init_db
from .models import TutorSession
from .services import event_engine, mine_engine, profile, sandbox, timeline, tutor

app = FastAPI(title="ACP Learning API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    mine_engine.load_patterns()


# ---- 请求/响应模型 ----

class CreateSessionReq(BaseModel):
    student_id: str
    pattern_id: str | None = None


class MessageReq(BaseModel):
    content: str


class SubmitReq(BaseModel):
    code: str


# ---- 会话（埋雷 + 共脑调试）----

def _cleanup_abandoned(db: Session, student_id: str):
    """清掉该学生"开了题但几乎没动"的废弃会话（停在①发现、planted、学生发言≤1）。
    每次开新题时顺手清，既清存量又防堆积；不碰真正进行中/已完成的会话。"""
    for s in db.query(TutorSession).filter_by(student_id=student_id, status="active",
                                              stage="①发现", mine_status="planted").all():
        stu_msgs = [m for m in (s.history or [])
                    if m["role"] == "user" and not m["content"].startswith(("（系统", "(系统"))]
        if len(stu_msgs) <= 1:
            db.delete(s)


@app.post("/api/sessions")
def create_session(req: CreateSessionReq, db: Session = Depends(get_db)):
    _cleanup_abandoned(db, req.student_id)
    pattern = mine_engine.pick_pattern(req.pattern_id)
    manifest = mine_engine.build_manifest(req.student_id, pattern)
    session = TutorSession(
        id=f"sess_{uuid.uuid4().hex[:12]}",
        student_id=req.student_id,
        pattern_id=pattern["id"],
        manifest=manifest,
        history=[],
    )
    db.add(session)
    profile.update_knowledge_state(
        db, student_id=req.student_id, pattern_id=pattern["id"],
        knowledge_points=pattern["knowledge_points"], new_state="已接触")
    db.commit()
    # 学生视角：只有代码，没有雷的信息
    return {
        "session_id": session.id,
        "language": pattern["language"],
        "code": pattern["buggy_code"],
        "task": "运行这段代码，看看它的行为是否符合预期。有问题就和导师讨论。",
    }


def _get_session(db: Session, session_id: str) -> TutorSession:
    session = db.get(TutorSession, session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    return session


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db)):
    """断点续做：返回会话当前状态，供前端刷新/重开后恢复界面（对话、阶段）。
    注意：学生未提交的代码编辑不持久化，恢复时代码区回到原始带雷代码。"""
    session = _get_session(db, session_id)
    mine = session.manifest["mines"][0]
    pattern = mine_engine.get_pattern(session.pattern_id)
    role_map = {"user": "student", "assistant": "tutor"}
    # 续做时过滤掉修复前留下的旧脏消息：导师虚构"你运行时…"那类（已修复，但老会话历史里还在）
    stale = ("你运行代码时", "你运行时", "你刚才运行", "你输入了什么", "你看到了什么报错")
    messages = [{"role": "system", "text": "运行这段代码，看看它的行为是否符合预期。有问题就和导师讨论。"}]
    for m in session.history:
        # 系统回流的占位消息（如"我提交的修复已通过测试"）不展示给学生
        if m["role"] == "user" and m["content"].startswith(("（系统", "(系统")):
            continue
        if m["role"] == "assistant" and any(s in m["content"] for s in stale):
            continue
        # 提交失败回流的整段代码，恢复时收成简短动作标记（与训练场内一致，避免大段代码刷屏）
        if m["role"] == "user" and m["content"].startswith(tutor.FIX_FAILED_PREFIX):
            messages.append({"role": "student", "text": "📤 我提交了一版修复"})
            continue
        messages.append({"role": role_map.get(m["role"], "system"), "text": m["content"]})
    return {
        "session_id": session.id,
        "pattern_id": session.pattern_id,
        "code": pattern["buggy_code"],
        "stage": session.stage,
        "hint_level": session.hint_level,
        "status": session.status,
        "fixed": session.mine_status in ("fixed", "internalized"),
        "done": session.status == "completed",
        "messages": messages,
        "internalize_questions": mine["internalize_questions"],
    }


@app.post("/api/sessions/{session_id}/run")
def run_code_endpoint(session_id: str, req: SubmitReq, db: Session = Depends(get_db)):
    """运行按钮：真跑一遍学生当前代码，返回真实输出/报错。纯观察，不判分、不改阶段。"""
    session = _get_session(db, session_id)
    r = sandbox.run_code(req.code)
    # 观测层：记一条执行事实（Debug Timeline）。run 无期望对比，kind 仅 RE/HANG/OK
    kind = "HANG" if r.timed_out else ("RE" if r.has_error else "OK")
    event_engine.log_execution(
        db, student_id=session.student_id, session_id=session.id,
        pattern_id=session.pattern_id, source="run", kind=kind, stderr=r.stderr,
        knowledge_points=mine_engine.get_pattern(session.pattern_id).get("knowledge_points", []))
    return {"stdout": r.stdout, "stderr": r.stderr, "timed_out": r.timed_out}


@app.post("/api/sessions/{session_id}/messages")
def send_message(session_id: str, req: MessageReq, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    if session.status != "active":
        raise HTTPException(409, "session already completed")
    return tutor.run_turn(db, session, req.content)


@app.post("/api/sessions/{session_id}/submit")
def submit_fix(session_id: str, req: SubmitReq, db: Session = Depends(get_db)):
    """④修复的判定走规则引擎，不走LLM（04文档：规则能判的绝不交给LLM）。
    失败的提交回流到导师对话做针对性引导；通过则进⑤验证，会话保持活跃。"""
    session = _get_session(db, session_id)
    if session.status != "active":
        raise HTTPException(409, "session already completed")
    mine = session.manifest["mines"][0]
    if session.mine_status == "fixed":
        return {"passed": True, "stage": session.stage, "message": "修复已通过，无需重复提交。"}

    result = mine_engine.judge_fix(session.pattern_id, req.code)
    # 观测层：记一条提交执行事实（Debug Timeline + Execution_Outcome），通过/失败都记
    kind_map = {"ok": "OK", "RE": "RE", "WA": "WA", "HANG": "HANG"}
    event_engine.log_execution(
        db, student_id=session.student_id, session_id=session.id,
        pattern_id=session.pattern_id, source="submit",
        kind=kind_map.get(result["kind"], result["kind"]), stderr=result.get("stderr", ""),
        knowledge_points=mine.get("knowledge_points", []))
    if not result["passed"]:
        diagnosis = tutor.judge_feedback(result)  # 真实运行结果（报错/输出差异/超时），非正则猜测
        fail_msg = (f"{tutor.FIX_FAILED_PREFIX}\n我提交的代码：\n{req.code}\n\n[真实运行结果] {diagnosis}")
        try:
            feedback = tutor.run_turn(db, session, fail_msg)
            return {"passed": False, "stage": feedback["stage"], "message": feedback["reply"]}
        except Exception:
            # LLM不可用时降级：失败记录仍进对话历史，下次对话导师能看到
            session.history = list(session.history) + [{"role": "user", "content": fail_msg}]
            db.commit()
            return {"passed": False, "stage": session.stage,
                    "message": f"测试未通过。{diagnosis}\n回到对话里和导师继续分析。"}

    # 学生若在讲清原因之前（还停在①②③）就直接提交了正确代码——不拦截，尊重已会的学生，
    # 但记下「跳过了理解对话」，反馈里温和提醒：修对≠学会，请在⑤⑥把「为什么」补上。
    skipped_understanding = STAGES.index(session.stage) < STAGES.index("④修复")

    session.mine_status = "fixed"
    session.stage = "⑤验证"
    # 导师主动开场：提交通过后直接抛出⑤验证的第一个问题，学生顺着答即可，不用自己猜该说什么。
    # 确定性生成（按题型的边界测试建议），不走 LLM——稳、零延迟。
    _cat = mine_engine.get_pattern(session.pattern_id)["category"]
    _sug = tutor.BOUNDARY_TEST_SUGGESTIONS.get(_cat, tutor.DEFAULT_BOUNDARY_SUGGESTION)
    _first = _sug.split("、")[0]
    tutor_opening = (f"漂亮，修好了！🎉 不过——通过这一次测试，不代表它在所有情况下都稳。"
                     f"我们一起验证一下：你觉得还该用哪些输入来测它？"
                     f"比如「{_first}」传进去会发生什么，你预期结果是什么？")
    session.history = list(session.history) + [
        {"role": "user", "content": "（系统：我提交的修复已通过测试）"},
        {"role": "assistant", "content": tutor_opening}]
    event_engine.on_mine_fixed(
        db, student_id=session.student_id, session_id=session.id,
        mine=mine, max_hint_level=session.hint_level)
    profile.update_knowledge_state(
        db, student_id=session.student_id, pattern_id=session.pattern_id,
        knowledge_points=mine["knowledge_points"], new_state="已解决")

    # V0.3 迁移检验：本题是某已内化题的变式，且学生以低提示（≤L1）独立解出 → 记「迁移已验证」
    transfer_confirmed = False
    src = profile.transfer_source(db, session.student_id, session.pattern_id)
    if src and session.hint_level in ("L0", "L1"):
        event_engine.on_transfer_confirmed(
            db, student_id=session.student_id, session_id=session.id,
            mine=mine, source_pattern=src, hint_level=session.hint_level)
        transfer_confirmed = True
    db.commit()
    if transfer_confirmed:
        message = ("测试通过，雷已排除！🎯 这是你已内化知识点的变式题，你独立解出来了——"
                   "说明你不只是会背，而是真的能把学到的道理用到新问题上。迁移能力已记入画像。"
                   "再和导师过一遍 ⑤验证 巩固一下。")
    elif skipped_understanding:
        message = ("测试通过，雷已排除！不过你是直接改对的——修好代码只算「已解决」。"
                   "真正学会是能讲清它为什么错：接下来和导师过一遍 ⑤验证与 ⑥内化（说清成因、定位、迁移），"
                   "知识点才会升级为「已内化」。")
    else:
        message = ("测试通过，雷已排除！进入⑤验证：和导师聊聊你会用哪些输入验证这次修复。"
                   "当前知识点状态是「已解决」——继续完成 ⑤验证与 ⑥内化（复述成因、定位、迁移）即可升级为「已内化」。")
    return {
        "passed": True,
        "stage": "⑤验证",
        "skipped_understanding": skipped_understanding,
        "transfer_confirmed": transfer_confirmed,
        "message": message,
        "tutor_opening": tutor_opening,
        "internalize_questions": mine["internalize_questions"],
    }


# ---- 画像（含下钻链路）----

@app.get("/api/students/{student_id}/profile")
def get_profile(student_id: str, db: Session = Depends(get_db)):
    return profile.get_profile(db, student_id)


@app.get("/api/students/{student_id}/timeline")
def get_timeline(student_id: str, db: Session = Depends(get_db)):
    """B1 调试成长轨迹（纯派生只读）：一道题=一个 Episode，串观察/尝试链/认知根因/收获。"""
    return timeline.build_timeline(db, student_id)


@app.get("/api/students/{student_id}/capabilities/{capability}/events")
def get_capability_events(student_id: str, capability: str, db: Session = Depends(get_db)):
    return profile.get_capability_events(db, student_id, capability)


@app.get("/api/students/{student_id}/recommendations")
def get_recommendations(student_id: str, db: Session = Depends(get_db)):
    patterns = list(mine_engine.load_patterns().values())
    return profile.recommend_patterns(db, student_id, patterns)


@app.get("/api/patterns/{pattern_id}/walkthrough")
def code_walkthrough(pattern_id: str, deep: bool = False):
    """逐行讲解该题代码（大白话、不剧透 bug），给零基础读懂代码用。deep=讲更细。"""
    if pattern_id not in mine_engine.load_patterns():
        raise HTTPException(404, "pattern not found")
    return {"pattern_id": pattern_id, "deep": deep,
            "walkthrough": tutor.explain_code(pattern_id, deep=deep)}


@app.get("/api/patterns")
def list_patterns():
    return [
        {"id": p["id"], "name": p["name"], "category": p["category"],
         "difficulty": p["difficulty"], "knowledge_points": p.get("knowledge_points", [])}
        for p in mine_engine.load_patterns().values()
    ]
