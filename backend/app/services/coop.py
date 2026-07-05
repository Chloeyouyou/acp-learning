"""AI 共脑调试（结对调试）· B0 预置样本（设计 09）。

与 Bug 闯关的根本区别：**系统不假装知道答案**。唯一可信的事实只有两样——
① 沙箱真跑出来的结果；② 学生自己说「我本来想要什么」。

B0 范围（已拍板）：只做预置样本，不做自带代码（那是 B1）。
- 复用：沙箱 run_code、运行结果注入（tutor.run_result_note/inject_run_note）、LLM client、
  pattern/session 的存储形状（样本≈伪 pattern，塞进 manifest，但标 mode="coop"）。
- **不复用**：六阶段 run_turn、Ground Truth 硬门控、judge_fix。走本文件的 coop 专用轻量导师。
- 完成判据：**学生点「解决了」是唯一门控**（静默逻辑错不报错，"报错消失"不能当判据）。
- 防污染：会话标 mode="coop"，timeline 跳过；ExecutionEvent 用 knowledge_points=[] 对画像隐形；
  不调 emit()、不动能力分。
"""

import uuid

from sqlalchemy.orm import Session

from ..config import TUTOR_MODEL
from ..models import ExecutionEvent, TutorSession, now
from . import process, tutor

# ---- 预置样本：单文件 Python，有 bug，「帮我看看这段哪儿不对」口吻 ----
# 样本自带 buggy code；无 expected_output / 无 fix_check（不判题）。
# B0 系统其实"知道"哪错，但导师按「只引导不给答案」走，绝不注入任何答案信息。
SAMPLES = {
    "off_by_one": {
        "kind": "wrong",
        "title": "求和结果好像少了一个",
        # ask = 学生口吻的首条求助，进会话即作为第一条消息
        "ask": "我想把一个列表里的数字全加起来，但算出来的结果好像不对，你能帮我看看这段哪儿不对吗？",
        "code": (
            "def total(xs):\n"
            "    s = 0\n"
            "    for i in range(len(xs) - 1):\n"
            "        s += xs[i]\n"
            "    return s\n"
            "\n"
            "print(total([1, 2, 3, 4]))\n"
        ),
    },
    "none_deref": {
        "kind": "crash",
        "title": "程序报错说什么 None",
        "ask": "我写了个函数找列表里第一个偶数，但运行就报错了，提到 None，我看不懂，帮我看看？",
        "code": (
            "def first_even(xs):\n"
            "    for x in xs:\n"
            "        if x % 2 == 0:\n"
            "            return x\n"
            "    # 没有偶数时没有 return\n"
            "\n"
            "result = first_even([1, 3, 5])\n"
            "print(result + 10)\n"
        ),
    },
    "infinite_loop": {
        "kind": "hang",
        "title": "程序跑不完、像卡住了",
        "ask": "我想从 5 一直数到 1 打印出来，但程序一运行就卡住不动了，帮我看看是怎么回事？",
        "code": (
            "n = 5\n"
            "while n > 0:\n"
            "    print(n)\n"
            "    # 想让 n 越来越小\n"
            "    n = n\n"
        ),
    },
    "key_error": {
        "kind": "crash",
        "title": "查价格时程序报错了",
        "ask": "我做了个价格表想查橙子多少钱，但一运行就报错，说什么 KeyError，帮我看看哪儿不对？",
        "code": (
            "prices = {\"苹果\": 3, \"香蕉\": 2}\n"
            "want = \"橙子\"\n"
            "print(want + \" 的价格是 \" + str(prices[want]) + \" 元\")\n"
        ),
    },
    "name_typo": {
        "kind": "crash",
        "title": "说找不到名字，可我明明写了",
        "ask": "我定义了变量想拼一句话打印，但程序说找不到名字，我看着明明都写了呀，帮我看看？",
        "code": (
            "greeting = \"早上好\"\n"
            "name = \"小明\"\n"
            "print(greeting + \"，\" + naem)\n"
        ),
    },
    "type_concat": {
        "kind": "crash",
        "title": "拼一句话却报类型错误",
        "ask": "我想拼一句带价格的话，但程序报错说 str 和 int 不能放一起，我不懂这是啥意思，帮我看看？",
        "code": (
            "def receipt(item, price):\n"
            "    return item + \" 共 \" + price + \" 元\"\n"
            "\n"
            "print(receipt(\"咖啡\", 18))\n"
        ),
    },
    "int_divide": {
        "kind": "wrong",
        "title": "算平均分，结果好像差一点",
        "ask": "我想算几个分数的平均，但算出来的数好像不太对，帮我看看哪儿有问题？",
        "code": (
            "def average(xs):\n"
            "    return sum(xs) // len(xs)\n"
            "\n"
            "print(\"平均分：\", average([90, 85, 88]))\n"
        ),
    },
}


# 样本现象标签（给零基础选题时一点引导，不泄答案）：报错的 / 不报错但结果不对 / 卡住
KIND_LABEL = {"crash": "⚠️ 会报错", "wrong": "🤔 不报错但结果不对", "hang": "⏳ 跑不完 / 卡住"}


def list_samples() -> list[dict]:
    """大厅/页面列出可选样本（不含答案信息）。带现象标签 kind/kind_label。"""
    out = []
    for sid, s in SAMPLES.items():
        kind = s.get("kind", "")
        out.append({"sample_id": sid, "title": s["title"],
                    "kind": kind, "kind_label": KIND_LABEL.get(kind, "")})
    return out


# ---- coop 轻量导师系统提示（独立，不碰 tutor.run_turn / 不注入 Ground Truth）----
COOP_SYSTEM = """你是一位结对调试伙伴，正和一个零基础学生一起看他的一段代码。你们是「共脑调试」——\
**你并不知道标准答案**，你只能依据两样真实信息说话：①对话里出现的「（系统·运行结果）」消息\
（学生真实点运行跑出来的）；②学生自己说出的「我本来想要什么」。

[最高红线·绝不臆断运行结果]
你不会运行代码。没有上面①那种真实运行结果时，你【绝不】断言任何输出、是否报错、循环走几次、\
返回什么值、"这样就对了/通过了"。要假设时只能用明确的「如果…」。需要知道某输入的真实结果时，\
就引导学生【点运行亲自跑出来】，结果会自动进对话，你再据此往下说。

[绝不给答案]
- 不写修改后的代码、表达式、整行或函数；不说"改成X / 应该写成X / 把A换成B / 加一行X / 删掉X"。
- 哪怕学生求你直接写、或卡很久——也只给【思路、方向、类比、反问】，让他自己写出来再运行。

[必须先问出「预期」]
很多 bug 是"能跑完但结果不对"（不报错）。这种情况你看到真实输出也无从判断对错，\
**除非先知道学生想要什么**。所以遇到结果类问题，先问：「你本来期望它输出/做到什么？」\
拿到他的预期，再和真实运行结果对照着一起分析。

[风格]
苏格拉底式、温和、一次一个小问题。先接住学生这一句，再往前推一步。讲到抽象概念配个生活化小例子。
不提"标准答案/正确做法"，不替学生总结结论。回复简短（2~4句），用中文。

[完成]
学生觉得搞定了会自己点「解决了」。你不要替他宣布"解决了/通过了"。"""


def _coop_session(db: Session, session_id: str) -> TutorSession:
    s = db.get(TutorSession, session_id)
    if s is None or (s.manifest or {}).get("mode") != "coop":
        return None
    return s


def start(db: Session, student_id: str, sample_id: str | None = None) -> dict:
    """用一个样本建一个 coop 会话（复用 TutorSession 存储，标 mode=coop）。"""
    if sample_id not in SAMPLES:
        sample_id = next(iter(SAMPLES))  # 没指定/非法 → 第一个样本
    sample = SAMPLES[sample_id]
    session = TutorSession(
        id=f"coop_{uuid.uuid4().hex[:12]}",
        student_id=student_id,
        pattern_id=f"coop_{sample_id}",  # 伪 id（B0 不碰 B1 的无雷哨兵）
        manifest={"mode": "coop", "sample_id": sample_id},
        # 首条 = 样本的学生求助（assistant 视角里它是"学生说的"，故 role=user）
        history=[{"role": "user", "content": sample["ask"]}],
    )
    db.add(session)
    db.commit()
    return {
        "session_id": session.id,
        "sample_id": sample_id,
        "title": sample["title"],
        "ask": sample["ask"],
        "code": sample["code"],
    }


# B1 自带代码：单文件 Python 文本上限（防超大输入；沙箱仍 subprocess + 4s 超时兜底）
MAX_CODE_LEN = 10000


def start_custom(db: Session, student_id: str, code: str, problem: str = "") -> dict | None:
    """B1：学生粘贴自己的单文件 Python 代码 + （可选）问题描述，建 custom coop 会话。
    code 存进 manifest 以便刷新/续做恢复（custom 没有预置样本可回退取）。"""
    code = (code or "").strip()
    if not code:
        return None
    code = code[:MAX_CODE_LEN]
    problem = (problem or "").strip()
    # 首条求助：有描述用描述，没有给一句默认（红线会让导师主动问出预期，不强制学生先填）
    ask = problem or "这是我自己写的代码，运行起来好像不太对，你能陪我一起看看哪儿有问题吗？"
    session = TutorSession(
        id=f"coop_{uuid.uuid4().hex[:12]}",
        student_id=student_id,
        pattern_id="coop_custom",   # 自带代码哨兵 id（不指向任何真 pattern）
        manifest={"mode": "coop", "custom": True, "code": code, "title": "我的代码"},
        history=[{"role": "user", "content": ask}],
    )
    db.add(session)
    db.commit()
    return {
        "session_id": session.id,
        "sample_id": None,
        "title": "我的代码",
        "ask": ask,
        "code": code,
    }


def get(db: Session, session_id: str) -> dict | None:
    """续做/刷新恢复：返回会话当前状态。"""
    s = _coop_session(db, session_id)
    if s is None:
        return None
    manifest = s.manifest or {}
    # 自带代码从 manifest 取 title/code；预置样本从 SAMPLES 取。首条求助 ask 已在 history[0]，
    # 渲染时自然带出，无需单独返回。
    if manifest.get("custom"):
        title, code = manifest.get("title", "我的代码"), manifest.get("code", "")
    else:
        sample = SAMPLES.get(manifest.get("sample_id"), {})
        title, code = sample.get("title", ""), sample.get("code", "")
    # 渲染消息：运行结果注入消息（以"（系统·运行结果）"开头）不在聊天区重复显示（终端已展示）
    messages = []
    for m in s.history:
        if m["role"] == "user" and m["content"].startswith(tutor.RUN_RESULT_PREFIX):
            continue
        role = "student" if m["role"] == "user" else "coop"
        messages.append({"role": role, "text": m["content"]})
    return {
        "session_id": s.id,
        "sample_id": manifest.get("sample_id"),
        "title": title,
        "code": code,
        "messages": messages,
        "status": s.status,
    }


def run(db: Session, session_id: str, code: str) -> dict | None:
    """coop 专用运行：不查 pattern（伪 id 会崩），跑沙箱 + 注入真实结果。
    knowledge_points=[]、mode=coop → 对画像/轨迹天然隐形。"""
    s = _coop_session(db, session_id)
    if s is None:
        return None
    return tutor.run_and_inject(db, s, code, knowledge_points=[], mode="coop")


def message(db: Session, session_id: str, content: str) -> dict | None:
    """一轮 coop 对话：拼历史 → 调 LLM（独立系统提示）→ append。LLM 失败优雅降级。"""
    s = _coop_session(db, session_id)
    if s is None:
        return None
    content = (content or "").strip()
    if not content:
        return {"reply": "你想说点什么？把你看到的、或者你本来期望它怎样，告诉我。"}
    history = list(s.history) + [{"role": "user", "content": content}]
    try:
        resp = tutor.client.chat.completions.create(
            model=TUTOR_MODEL,
            messages=[{"role": "system", "content": COOP_SYSTEM}, *history],
            temperature=0.3, max_tokens=600,
        )
        reply = (resp.choices[0].message.content or "").strip()
        if not reply:
            raise ValueError("empty reply")
    except Exception:
        # 降级：不臆断、不崩，引导学生先跑一下把真实结果带回来
        reply = "我这会儿有点没接住——你先点一下「运行」，把真实结果跑出来，再把它发我，我们一起看。"
    s.history = history + [{"role": "assistant", "content": reply}]
    s.touch()
    # 过程化时间线（写新）：coop 对话也记，供回放
    process.record_message(db, s.id, "student", content, "chat")
    process.record_message(db, s.id, "tutor", reply, "chat")
    db.commit()
    return {"reply": reply}


def resolve(db: Session, session_id: str) -> dict | None:
    """学生点「解决了」——唯一完成门控。把会话标完成。"""
    s = _coop_session(db, session_id)
    if s is None:
        return None
    if s.status == "active":
        s.status = "completed"
        s.touch()
        _log_collab_signal(db, s)   # B2 埋点：记结构化协作信号（不进画像，攒数据待将来开分）
        db.commit()
    return {"status": s.status}


def _log_collab_signal(db: Session, s: TutorSession) -> None:
    """B2 埋点（先记录、不计分，用户拍板）：会话完成时，若学生真在「结对+动手验证」，
    记一条协作事实日志。纯 ExecutionEvent——append-only、knowledge_points=[]、mode=coop，
    绝不碰 capability_scores / 画像 / 成长轨迹。将来 B2 开分时，calculator 读它即可一行开启。"""
    runs = db.query(ExecutionEvent).filter_by(session_id=s.id, source="run").count()
    turns = sum(1 for m in (s.history or [])
                if m.get("role") == "user" and not m["content"].startswith(tutor.RUN_RESULT_PREFIX))
    if runs < 1:
        return   # 没动手运行验证过 → 不算一次有效的 AI 协作调试，不埋点
    db.add(ExecutionEvent(
        id=f"ex_{uuid.uuid4().hex[:16]}", version="v1",
        student_id=s.student_id, session_id=s.id, pattern_id=s.pattern_id,
        source="coop_resolve", kind="COLLAB", error_family=None, knowledge_points=[],
        meta={"mode": "coop", "collab": {"runs": runs, "turns": turns},
              "ontology_tags": [], "trace_snapshot_id": None,
              "stderr_summary": None, "stdout_summary": None},
        timestamp=now(),
    ))
