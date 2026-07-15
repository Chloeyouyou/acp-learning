"""ACP Learning 后端 MVP。

闭环：埋雷（创建会话）→ AI共脑对话 → 提交修复（规则判定）→ 事件 → 画像。
"""

import hmac
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .concurrency import session_turn
from .config import STAGES
from .db import get_db, init_db
from .models import ExecutionEvent, Student, TutorSession
from .runtime_security import security_status, validate_production_environment
from .security import sign_token, verify_token
from .services import (
    action_governance, coop, curriculum, event_engine, learning_path, mine_engine, presence,
    process, profile, question_training, review, teacher, timeline, tutor,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：迁移到最新 + 预载题库（替代已废弃的 @app.on_event("startup")，审计 #6）
    validate_production_environment()
    init_db()
    mine_engine.load_patterns()
    # 抬高同步端点线程池上限：一次 LLM 对话最长占一个线程 ~30s，默认 40 令牌在满班时
    # 会被对话请求占满、拖慢查画像/运行等快端点。64 够一个班 + 余量，又不至于让 SQLite 写抖动。
    try:
        import anyio
        anyio.to_thread.current_default_thread_limiter().total_tokens = 64
    except Exception:
        pass
    yield


app = FastAPI(title="ACP Learning API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- 身份 / 鉴权（M1 D2-3）----

class LoginReq(BaseModel):
    student_id: str
    name: str = ""


def current_student(authorization: str | None = Header(default=None),
                    db: Session = Depends(get_db)) -> str:
    """从 Authorization: Bearer <token> 解出学号（校验 HMAC 签名）。无/坏 token → 401。
    这是所有需要身份的端点的唯一可信学号来源——绝不再信 URL/请求体里自报的 student_id。"""
    token = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
    sid = verify_token(token)
    if not sid:
        raise HTTPException(401, "未登录或登录已失效")
    return sid


def require_self(path_student_id: str, me: str) -> None:
    """越权门：路径里的学号必须等于 token 学号，否则 403。挡「改 URL 看别人数据」（IDOR）。"""
    if path_student_id != me:
        raise HTTPException(403, "无权访问他人数据")


def turn_lock(session_id: str):
    """会话回合锁依赖：进端点前独占本会话、出端点后释放。加在会写会话的端点上，
    串行化同会话并发请求——防丢消息 + 堵 submit TOCTOU（审计 #12）。见 concurrency.py。"""
    with session_turn(session_id):
        yield


def _check_admin(token: str | None = None, authorization: str | None = None) -> None:
    """作者/教师鉴权：优先 Authorization Bearer；query token 仅保留旧 QA 链接兼容。"""
    required = os.environ.get("ACP_ADMIN_TOKEN")
    header_token = (authorization[7:].strip()
                    if authorization and authorization.startswith("Bearer ") else None)
    candidate = header_token or token
    if not required or not hmac.compare_digest(candidate or "", required):
        raise HTTPException(403, "forbidden")


@app.post("/api/auth/login")
def login(req: LoginReq, db: Session = Depends(get_db)):
    """轻量登录（无密码）：输学号即签发 token。首次登录 upsert students 行。
    学号是稳定身份——换设备/清缓存后输同一学号即找回全部进度。"""
    sid = req.student_id.strip()
    if not sid:
        raise HTTPException(400, "学号不能为空")
    row = db.get(Student, sid)
    if row is None:
        db.add(Student(id=sid, name=req.name.strip()))
    elif req.name.strip():
        row.name = req.name.strip()   # 允许补/改姓名
    db.commit()
    return {"token": sign_token(sid), "student_id": sid, "name": req.name.strip()}


# ---- 请求/响应模型 ----

class CreateSessionReq(BaseModel):
    pattern_id: str | None = None
    mode: str = "debug"  # debug（默认）/ review（复习）；coop 后续


class MessageReq(BaseModel):
    content: str


class SubmitReq(BaseModel):
    code: str


# ---- 会话（埋雷 + 共脑调试）----

def _cleanup_abandoned(db: Session, student_id: str):
    """清掉该学生「开了题但完全没动」的纯空壳会话——四条全满足才删：
    ① status=active ② mine_status=planted（连雷都没定位）③ 零 ExecutionEvent（没 run/submit）
    ④ 零真实学生消息（history 只有系统消息）。
    宁可漏清不可误删：有任何真实对话/运行/提交的会话一律保留（哪怕一句真实发言也是学习痕迹）。"""
    for s in db.query(TutorSession).filter_by(student_id=student_id, status="active",
                                              mine_status="planted").all():
        stu_msgs = [m for m in (s.history or [])
                    if m["role"] == "user" and not m["content"].startswith(("（系统", "(系统"))]
        if stu_msgs:
            continue  # 有真实学生发言 → 保留
        if db.query(ExecutionEvent.id).filter_by(session_id=s.id).first() is not None:
            continue  # 有运行/提交记录 → 保留
        db.delete(s)


@app.post("/api/sessions")
def create_session(req: CreateSessionReq, db: Session = Depends(get_db),
                   me: str = Depends(current_student)):
    _cleanup_abandoned(db, me)
    pattern = mine_engine.pick_pattern_for_student(me, req.pattern_id, db)
    manifest = mine_engine.build_manifest(me, pattern)
    manifest["mode"] = req.mode  # 玩法模式寄存在 manifest（零 schema 迁移）
    session = TutorSession(
        id=f"sess_{uuid.uuid4().hex[:12]}",
        student_id=me,
        pattern_id=pattern["id"],
        manifest=manifest,
        history=[],
    )
    db.add(session)
    profile.update_knowledge_state(
        db, student_id=me, pattern_id=pattern["id"],
        knowledge_points=pattern["knowledge_points"], new_state="已接触")
    db.commit()
    # 开题前干预（Intervention）：该题命中用户跨题高频思维默认值时，带回一句赋能提醒（否则 None）
    intervention = timeline.intervention_for(db, me, pattern["id"])
    # 学生视角：只有代码，没有雷的信息
    return {
        "session_id": session.id,
        "pattern_id": pattern["id"],   # 智能开题（不指定题）时，前端据此知道选中了哪道
        "language": pattern["language"],
        "code": pattern["buggy_code"],
        "task": "运行这段代码，看看它的行为是否符合预期。有问题就和导师讨论。",
        "intervention": intervention,
    }


def _get_session(db: Session, session_id: str, me: str) -> TutorSession:
    session = db.get(TutorSession, session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    # 会话归属校验：session_id 虽是不可枚举 uuid，有身份后仍强制只能操作自己的会话
    if session.student_id != me:
        raise HTTPException(403, "无权访问他人会话")
    return session


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db),
                me: str = Depends(current_student)):
    """断点续做：返回会话当前状态，供前端刷新/重开后恢复界面（对话、阶段）。
    注意：学生未提交的代码编辑不持久化，恢复时代码区回到原始带雷代码。"""
    session = _get_session(db, session_id, me)
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
            if "[真实运行结果]" in m["content"]:
                real_result = m["content"].split("[真实运行结果]", 1)[1].strip()
                messages.append({"role": "system", "text": f"提交测试结果：{real_result}"})
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
def run_code_endpoint(session_id: str, req: SubmitReq, db: Session = Depends(get_db),
                      me: str = Depends(current_student), _lock: None = Depends(turn_lock)):
    """运行按钮：真跑一遍学生当前代码，返回真实输出/报错。纯观察，不判分、不改阶段。"""
    session = _get_session(db, session_id, me)
    kps = mine_engine.get_pattern(session.pattern_id).get("knowledge_points", [])
    return tutor.run_and_inject(db, session, req.code, knowledge_points=kps,
                                mode=(session.manifest or {}).get("mode", "debug"))


@app.post("/api/sessions/{session_id}/messages")
def send_message(session_id: str, req: MessageReq, db: Session = Depends(get_db),
                 me: str = Depends(current_student), _lock: None = Depends(turn_lock)):
    session = _get_session(db, session_id, me)
    if session.status != "active":
        raise HTTPException(409, "session already completed")
    return tutor.run_turn(db, session, req.content)


@app.post("/api/sessions/{session_id}/submit")
def submit_fix(session_id: str, req: SubmitReq, db: Session = Depends(get_db),
               me: str = Depends(current_student), _lock: None = Depends(turn_lock)):
    """④修复的判定走规则引擎，不走LLM（04文档：规则能判的绝不交给LLM）。
    失败的提交回流到导师对话做针对性引导；通过则进⑤验证，会话保持活跃。"""
    session = _get_session(db, session_id, me)
    if session.status != "active":
        raise HTTPException(409, "session already completed")
    mine = session.manifest["mines"][0]
    if session.mine_status == "fixed":
        return {"passed": True, "stage": session.stage, "message": "修复已通过，无需重复提交。"}

    action_context = action_governance.authorize_action(
        actor_id=session.student_id,
        session_id=session.id,
        action="submission.judge",
        purpose="judge_submission",
        initiated_by="student",
        payload={"code": req.code, "mode": (session.manifest or {}).get("mode", "debug"),
                 "pattern_id": session.pattern_id},
    )
    result = mine_engine.judge_fix(session.pattern_id, req.code)
    action_context = action_governance.with_execution(action_context, "completed")
    # 观测层：记一条提交执行事实（Debug Timeline + Execution_Outcome），通过/失败都记
    kind_map = {"ok": "OK", "RE": "RE", "WA": "WA", "HANG": "HANG"}
    execution = event_engine.log_execution(
        db, student_id=session.student_id, session_id=session.id,
        pattern_id=session.pattern_id, source="submit",
        kind=kind_map.get(result["kind"], result["kind"]), stderr=result.get("stderr", ""),
        knowledge_points=mine.get("knowledge_points", []),
        mode=(session.manifest or {}).get("mode", "debug"),
        action_context=action_context)
    # 过程化：记提交时的代码快照，链到本次执行事实（submit 的代码链）
    snap = process.record_snapshot(db, session, req.code, execution.id)
    process.record_message(db, session.id, "student",
                           f"（提交修复：{'通过' if result['passed'] else '未通过'}）", "submit")
    db.commit()
    execution_summary = {
        "kind": execution.kind,
        "error_family": execution.error_family,
        "bug_type": (execution.meta or {}).get("bug_type"),
        "concept_tags": (execution.meta or {}).get("concept_tags", []),
        "hint": tutor.explain_error(execution.kind, result.get("stderr", "")),   # 报错翻译成人话
    }
    if not result["passed"]:
        diagnosis = tutor.judge_feedback(result)  # 真实运行结果（报错/输出差异/超时），非正则猜测
        change_note = process.diff_summary(snap.diff_stats)  # 改动分析：盲改 vs 定向改
        fail_msg = (f"{tutor.FIX_FAILED_PREFIX}\n我提交的代码：\n{req.code}\n\n[真实运行结果] {diagnosis}")
        if change_note:
            fail_msg += f"\n[改动分析] {change_note}"
        try:
            feedback = tutor.run_turn(db, session, fail_msg)
            return {"passed": False, "stage": feedback["stage"], "message": feedback["reply"],
                    "execution": execution_summary, "action_context": action_context}
        except Exception:
            # LLM不可用时降级：失败记录仍进对话历史，下次对话导师能看到
            session.history = list(session.history) + [{"role": "user", "content": fail_msg}]
            session.touch()
            db.commit()
            return {"passed": False, "stage": session.stage,
                    "message": f"测试未通过。{diagnosis}\n回到对话里和导师继续分析。",
                    "execution": execution_summary, "action_context": action_context}

    # 学生若在讲清原因之前（还停在①②③）就直接提交了正确代码——不拦截，尊重已会的学生，
    # 但记下「跳过了理解对话」，反馈里温和提醒：修对≠学会，请在⑤⑥把「为什么」补上。
    skipped_understanding = STAGES.index(session.stage) < STAGES.index("④修复")

    session.mine_status = "fixed"
    session.stage = "⑤验证"
    session.touch()   # 提交通过是一次活动，刷新最近活跃时间
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
    process.record_message(db, session.id, "tutor", tutor_opening, "tutor_opening")  # 时间线（写新）
    # 复习模式：老题重解不再发能力增益事件，否则反复复习同一题会刷高 Debug 能力分、污染数字孪生。
    # 执行事实（ExecutionEvent，已带 meta.mode=review）照常记——驱动间隔升档，留存信号留待将来单独消费。
    is_review = (session.manifest or {}).get("mode") == "review"
    transfer_confirmed = False
    if not is_review:
        event_engine.on_mine_fixed(
            db, student_id=session.student_id, session_id=session.id,
            mine=mine, max_hint_level=session.hint_level,
            action_context=action_context)
        profile.update_knowledge_state(
            db, student_id=session.student_id, pattern_id=session.pattern_id,
            knowledge_points=mine["knowledge_points"], new_state="已解决")

        # V0.3 迁移检验：本题是某已内化题的变式，且学生以低提示（≤L1）独立解出 → 记「迁移已验证」
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
        "action_context": action_context,
    }


# ---- 画像（含下钻链路）----

@app.get("/api/students/{student_id}/profile")
def get_profile(student_id: str, db: Session = Depends(get_db),
                me: str = Depends(current_student)):
    require_self(student_id, me)
    return profile.get_profile(db, student_id)


@app.get("/api/students/{student_id}/presence")
def get_presence(student_id: str, db: Session = Depends(get_db),
                 me: str = Depends(current_student)):
    """灵犀感知层（设计 11）：该生最近活跃时间，供大厅「久别回来/新朋友」招呼。纯只读派生。"""
    require_self(student_id, me)
    return presence.presence_signals(db, student_id)


@app.get("/api/students/{student_id}/timeline")
def get_timeline(student_id: str, db: Session = Depends(get_db),
                 me: str = Depends(current_student)):
    """B1 调试成长轨迹（纯派生只读）：一道题=一个 Episode，串观察/尝试链/认知根因/收获。"""
    require_self(student_id, me)
    return timeline.build_timeline(db, student_id)


@app.get("/api/students/{student_id}/review-queue")
def get_review_queue(student_id: str, db: Session = Depends(get_db),
                     me: str = Depends(current_student)):
    """今日复习队列（间隔重复，纯派生只读）：哪些已解决/已内化的题到期该回看。"""
    require_self(student_id, me)
    return {"due": review.due_queue(db, student_id)}


@app.get("/api/students/{student_id}/active-sessions")
def get_active_sessions(student_id: str, db: Session = Depends(get_db),
                        me: str = Depends(current_student)):
    """未完成关卡列表（最近 5 个 active 会话摘要），供大厅续做。纯只读、不写库。
    按 updated_at（每次对话/运行/提交刷新）倒序——真按活跃度，不再每会话回查 ExecutionEvent。"""
    require_self(student_id, me)
    return {"sessions": learning_path.active_session_summaries(db, student_id)}


@app.get("/api/students/{student_id}/next-action")
def get_next_action(student_id: str, db: Session = Depends(get_db),
                    me: str = Depends(current_student)):
    """统一、可解释的续学行动。训练大厅与成长页共用，纯派生只读。"""
    require_self(student_id, me)
    return learning_path.build_next_action(db, student_id)


@app.get("/api/sessions/{session_id}/replay")
def get_replay(session_id: str, db: Session = Depends(get_db),
               me: str = Depends(current_student)):
    """过程回放：这道题的代码逐版 + 对话/运行/提交时间线（纯派生只读）。只能看自己的会话。"""
    _get_session(db, session_id, me)   # 归属校验（404/403）
    return process.build_replay(db, session_id)


@app.post("/api/sessions/{session_id}/abandon")
def abandon_session(session_id: str, db: Session = Depends(get_db),
                    me: str = Depends(current_student), _lock: None = Depends(turn_lock)):
    """显式放弃一道未完成关卡：只把 status 置 abandoned，**不删 history / 事件**。
    放弃后不再出现在 active-sessions 列表里，但历史与事件流完整保留。"""
    session = _get_session(db, session_id, me)
    if session.status == "active":
        session.status = "abandoned"
        db.commit()
    return {"session_id": session.id, "status": session.status}


@app.get("/api/admin/students/{student_id}/sessions")
def admin_list_sessions(student_id: str, token: str | None = None,
                        authorization: str | None = Header(default=None),
                        db: Session = Depends(get_db)):
    """【作者/QA 只读】按学号列出全部会话 + 完整对话历史 + 内化判定，供复盘任何一局。

    学生端不链接、不使用——仅作者直连 URL 或工具调用。安全：默认拒绝——必须设置环境变量
    ACP_ADMIN_TOKEN 且请求带匹配的 Authorization Bearer 才放行（query 仅兼容旧 QA 链接）。
    未设 ACP_ADMIN_TOKEN 一律 403——绝不默认放行，避免忘配一次就全员对话史外泄。
    本地 QA：先设置 ACP_ADMIN_TOKEN，再带 `Authorization: Bearer xxx` 访问。
    """
    _check_admin(token, authorization)
    sessions = (db.query(TutorSession).filter_by(student_id=student_id)
                .order_by(TutorSession.created_at.desc()).all())
    return [
        {
            "session_id": s.id,
            "pattern_id": s.pattern_id,
            "mode": (s.manifest or {}).get("mode", "debug"),
            "stage": s.stage,
            "mine_status": s.mine_status,
            "status": s.status,
            "hint_level": s.hint_level,
            "internalize_scores": s.internalize_scores,
            "created_at": s.created_at,
            "history": s.history,
        }
        for s in sessions
    ]


@app.get("/api/students/{student_id}/capabilities/{capability}/events")
def get_capability_events(student_id: str, capability: str, db: Session = Depends(get_db),
                          me: str = Depends(current_student)):
    require_self(student_id, me)
    return profile.get_capability_events(db, student_id, capability)


@app.get("/api/students/{student_id}/recommendations")
def get_recommendations(student_id: str, db: Session = Depends(get_db),
                        me: str = Depends(current_student)):
    require_self(student_id, me)
    patterns = list(mine_engine.load_patterns().values())
    return profile.recommend_patterns(db, student_id, patterns)


@app.get("/api/patterns/{pattern_id}/walkthrough")
def code_walkthrough(pattern_id: str, deep: bool = False):
    """逐行讲解该题代码（大白话、不剧透 bug），给零基础读懂代码用。deep=讲更细。"""
    if pattern_id not in mine_engine.load_patterns():
        raise HTTPException(404, "pattern not found")
    return {"pattern_id": pattern_id, "deep": deep,
            "walkthrough": tutor.explain_code(pattern_id, deep=deep)}


class DiagnoseReq(BaseModel):
    scenario_id: str
    prompt: str


class DiagnoseResp(BaseModel):
    phenomenon: bool
    context: bool
    expectation: bool
    score: int
    feedback: str
    confidence: float
    degraded: bool = False


@app.post("/api/question-training/diagnose", response_model=DiagnoseResp)
def diagnose_question(req: DiagnoseReq, db: Session = Depends(get_db),
                      me: str = Depends(current_student)):
    """提问训练（docs/design/12）：诊断提问的三要素完整度 + 给分 + 反馈。
    只评价提问本身，不替学生答技术问题、不臆断运行结果。
    P1-lite：诊断后沉淀为 ExecutionEvent 数字资产（只记事实）。学生身份取自 token。
    P1-full：再记一条 Prompt_Design 能力事件进画像（日上限/同句去重/低置信不计分）。"""
    result = question_training.diagnose(req.scenario_id, req.prompt)
    if req.prompt.strip():
        question_training.log_diagnosis(
            db, student_id=me, scenario_id=req.scenario_id,
            prompt=req.prompt, result=result)
        question_training.score_diagnosis(
            db, student_id=me, scenario_id=req.scenario_id,
            prompt=req.prompt, result=result)
    return result


@app.get("/api/students/{student_id}/question-training/weakness")
def question_weakness(student_id: str, db: Session = Depends(get_db),
                      me: str = Depends(current_student)):
    """回放该生 qt_diagnose 资产，返回最近最常漏的要素（短板个性化）；样本不足返回 null。"""
    require_self(student_id, me)
    return {"weakness": question_training.weakness_summary(db, student_id)}


# ---- AI 共脑调试（结对调试）· B0 预置样本（设计 09，与闯关端点隔离）----

class CoopStartReq(BaseModel):
    sample_id: str | None = None


class CoopStartCustomReq(BaseModel):
    code: str
    problem: str = ""


class CoopWalkReq(BaseModel):
    code: str
    deep: bool = False


@app.get("/api/coop/samples")
def coop_samples():
    """列出可选的结对调试样本（不含答案信息）。"""
    return {"samples": coop.list_samples()}


@app.post("/api/coop/start")
def coop_start(req: CoopStartReq, db: Session = Depends(get_db),
               me: str = Depends(current_student)):
    return coop.start(db, me, req.sample_id)


@app.post("/api/coop/start-custom")
def coop_start_custom(req: CoopStartCustomReq, db: Session = Depends(get_db),
                      me: str = Depends(current_student)):
    """B1：学生粘贴自己的单文件 Python 代码（+可选问题描述），结对调试。"""
    out = coop.start_custom(db, me, req.code, req.problem)
    if out is None:
        raise HTTPException(400, "code 不能为空")
    return out


def _own_coop(db: Session, session_id: str, me: str) -> None:
    """coop 会话归属校验：coop 会话也是 TutorSession 行，复用 _get_session 的 owner 门。"""
    _get_session(db, session_id, me)


@app.get("/api/coop/{session_id}")
def coop_get(session_id: str, db: Session = Depends(get_db),
             me: str = Depends(current_student)):
    _own_coop(db, session_id, me)
    out = coop.get(db, session_id)
    if out is None:
        raise HTTPException(404, "coop session not found")
    return out


@app.post("/api/coop/{session_id}/run")
def coop_run(session_id: str, req: SubmitReq, db: Session = Depends(get_db),
             me: str = Depends(current_student), _lock: None = Depends(turn_lock)):
    """coop 运行：真跑学生当前代码，真实结果注入对话。不查 pattern、不判题。"""
    _own_coop(db, session_id, me)
    out = coop.run(db, session_id, req.code)
    if out is None:
        raise HTTPException(404, "coop session not found")
    return out


@app.post("/api/coop/{session_id}/message")
def coop_message(session_id: str, req: MessageReq, db: Session = Depends(get_db),
                 me: str = Depends(current_student), _lock: None = Depends(turn_lock)):
    _own_coop(db, session_id, me)
    out = coop.message(db, session_id, req.content)
    if out is None:
        raise HTTPException(404, "coop session not found")
    return out


@app.post("/api/coop/{session_id}/resolve")
def coop_resolve(session_id: str, db: Session = Depends(get_db),
                 me: str = Depends(current_student), _lock: None = Depends(turn_lock)):
    """学生点「解决了」——结对调试唯一完成门控。"""
    _own_coop(db, session_id, me)
    out = coop.resolve(db, session_id)
    if out is None:
        raise HTTPException(404, "coop session not found")
    return out


@app.post("/api/coop/walkthrough")
def coop_walkthrough(req: CoopWalkReq):
    """逐行讲解 coop 当前代码（样本/自带代码无 pattern_id，按 code 内容讲）。"""
    return {"walkthrough": tutor.walkthrough_for_code(req.code, req.deep)}


@app.get("/api/health")
def health():
    """探活端点（Render 健康检查 / 自检用）。sandbox 字段暴露实际生效的沙箱后端——
    线上应为 docker；若显示 subprocess 说明容器没能连到宿主 docker（学生代码未隔离），需排查。"""
    from .services import sandbox
    runtime = security_status()
    return {
        "status": "ok" if runtime["ready"] else "unsafe",
        "version": "0.1.0",
        "sandbox": sandbox.active_backend(),
        "environment": runtime["environment"],
        "security_ready": runtime["ready"],
    }


@app.get("/api/curriculum")
def get_curriculum(db: Session = Depends(get_db), me: str = Depends(current_student)):
    """课程地图（M3b，纯派生只读）：单元 → 关卡 + 本人进度（身份取自 token）。"""
    return curriculum.build_curriculum(db, me)


@app.get("/api/teacher/overview")
def teacher_overview(token: str | None = None, class_id: str | None = None,
                     authorization: str | None = Header(default=None),
                     db: Session = Depends(get_db)):
    """【教师只读】全班总览（M4）：每人进度/最近活跃/正卡在哪。纯派生。
    鉴权复用 ACP_ADMIN_TOKEN（Authorization Bearer）；不传 class_id 看全体，传了按班过滤。"""
    _check_admin(token, authorization)
    return teacher.build_class_overview(db, class_id)


@app.get("/api/teacher/students/{student_id}")
def teacher_student_detail(student_id: str, token: str | None = None,
                           authorization: str | None = Header(default=None),
                           db: Session = Depends(get_db)):
    """【教师只读】钻取单个学生的进度、最近会话和教学策略效果。"""
    _check_admin(token, authorization)
    detail = teacher.build_student_detail(db, student_id)
    if detail is None:
        raise HTTPException(404, "student not found")
    return detail


@app.get("/api/teacher/sessions/{session_id}/replay")
def teacher_session_replay(session_id: str, token: str | None = None,
                           authorization: str | None = Header(default=None),
                           db: Session = Depends(get_db)):
    """【教师只读】查看任意学生单局回放；仍只读同一份 append-only 事实。"""
    _check_admin(token, authorization)
    replay = process.build_replay(db, session_id)
    if replay is None:
        raise HTTPException(404, "session not found")
    return replay


@app.get("/api/patterns")
def list_patterns():
    return [
        {"id": p["id"], "name": p["name"], "category": p["category"],
         "difficulty": p["difficulty"], "knowledge_points": p.get("knowledge_points", [])}
        for p in mine_engine.load_patterns().values()
    ]


# ---- 部署：单服务同时托管前端（构建后的 frontend/dist）。本地开发无 dist 时自动跳过 ----
# 注意：必须放在所有 /api 路由之后注册，SPA 兜底不会吃掉 API。
from pathlib import Path as _Path  # noqa: E402

from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

_DIST = _Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if (_DIST / "index.html").is_file():
    if (_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def _spa(full_path: str):
        """非 /api 的请求：有对应静态文件就返回，否则回 index.html（history 路由兜底）。"""
        if full_path.startswith("api/") or full_path == "api":
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        # 安全：解析真实路径并校验仍在 dist 内，挡 ../ 路径穿越（否则 ../../backend/.env 可读到密钥）
        candidate = (_DIST / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(_DIST.resolve()):
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
