"""ACP Learning 后端 MVP。

闭环：埋雷（创建会话）→ AI共脑对话 → 提交修复（规则判定）→ 事件 → 画像。
"""

import uuid

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import get_db, init_db
from .models import TutorSession
from .services import event_engine, mine_engine, profile, tutor

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

@app.post("/api/sessions")
def create_session(req: CreateSessionReq, db: Session = Depends(get_db)):
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


@app.post("/api/sessions/{session_id}/messages")
def send_message(session_id: str, req: MessageReq, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    if session.status != "active":
        raise HTTPException(409, "session already completed")
    return tutor.run_turn(db, session, req.content)


@app.post("/api/sessions/{session_id}/submit")
def submit_fix(session_id: str, req: SubmitReq, db: Session = Depends(get_db)):
    """④修复的判定走规则引擎，不走LLM（04文档：规则能判的绝不交给LLM）。"""
    session = _get_session(db, session_id)
    mine = session.manifest["mines"][0]

    if not mine_engine.verify_fix(session.pattern_id, req.code):
        return {"passed": False, "message": "测试仍然失败，回到导师对话继续分析。"}

    session.mine_status = "fixed"
    session.stage = "⑥内化"
    session.status = "completed"  # MVP：内化关1留给下个迭代，先结算
    event_engine.on_mine_fixed(
        db, student_id=session.student_id, session_id=session.id,
        mine=mine, max_hint_level=session.hint_level)
    profile.update_knowledge_state(
        db, student_id=session.student_id, pattern_id=session.pattern_id,
        knowledge_points=mine["knowledge_points"], new_state="已解决")
    db.commit()
    return {
        "passed": True,
        "message": "测试通过。注意：当前状态是「已解决」——要升级为「已内化」，还需通过反向提问与变式（V0.3）。",
        "internalize_questions": mine["internalize_questions"],
    }


# ---- 画像（含下钻链路）----

@app.get("/api/students/{student_id}/profile")
def get_profile(student_id: str, db: Session = Depends(get_db)):
    return profile.get_profile(db, student_id)


@app.get("/api/students/{student_id}/capabilities/{capability}/events")
def get_capability_events(student_id: str, capability: str, db: Session = Depends(get_db)):
    return profile.get_capability_events(db, student_id, capability)


@app.get("/api/patterns")
def list_patterns():
    return [
        {"id": p["id"], "name": p["name"], "category": p["category"], "difficulty": p["difficulty"]}
        for p in mine_engine.load_patterns().values()
    ]
