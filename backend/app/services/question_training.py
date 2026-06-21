"""提问训练 P0（docs/design/12）。

只诊断「提问本身」的三要素完整度（现象 / 上下文 / 预期），给分 + 反馈。
P0 边界：不调 event_engine、不落 Prompt_Design、不动画像、不复用六阶段逻辑。
仅复用 LLM client（tutor.client / TUTOR_MODEL）。LLM 不可用时温和降级，绝不让页面崩。
"""

import json
import uuid

from sqlalchemy.orm import Session

from ..config import TUTOR_MODEL
from ..models import Event, ExecutionEvent, now
from . import event_engine, tutor

# P1-lite 资产化用的命名空间常量（doc12）——确保对画像/成长轨迹双隐形
QT_SOURCE = "qt_diagnose"
QT_PATTERN_ID = "QUESTION_TRAINING"
QT_KIND = "QT"
CONFIDENCE_MIN = 0.7  # 短板统计的置信门槛（与画像同口径）

# P1-full 计分（doc12 / 04文档 §4.9）
QT_SESSION_PREFIX = "qtsess_"
DAILY_POSITIVE_CAP = 6  # Prompt_Design 每日正向 delta 合计封顶（04文档 §5.5）
# 三要素齐全度 → delta：3项+2 / 2项+1 / 1项0(不记) / 0项(纯"帮我看看")-1
_DELTA_BY_FACTORS = {3: 2, 2: 1, 1: 0, 0: -1}

# 预置场景：每个给一句背景，学生据此写提问。前端也用同一份（id 对齐）。
SCENARIOS = {
    "login": {
        "title": "登录功能跑不通",
        "brief": "你在做一个登录功能，点登录后没反应或报错。把这件事问清楚，让 AI 能直接帮上忙。",
    },
    "list_empty": {
        "title": "列表页一直空白",
        "brief": "你的页面应该显示一个列表，但运行后一直是空白，数据出不来。",
    },
    "wrong_result": {
        "title": "函数算出来的结果不对",
        "brief": "你写了个函数做计算，但它返回的数和你预期的对不上。",
    },
    # 自带真实问题（P2-A）：无预置背景，LLM 只就学生自己写的文本判三要素
    "custom": {
        "title": "我自己的问题",
        "brief": "",
    },
}

SYSTEM = (
    "你是「知返」，一个教初学者『把问题问清楚』的提问教练。"
    "你的唯一任务是诊断学生写给 AI 的【提问本身】好不好，而不是去回答这个技术问题。\n"
    "评判一个好提问是否包含三要素（面向零基础，宽松计入：只要学生给了该要素的【具体信息】就算有，"
    "不要求专业表述或完整）：\n"
    "1) 现象 phenomenon：报了什么错或看到什么实际表现。"
    "学生写出错误类型(如 NullPointerException)、或具体描述了发生什么(如『点了没反应』『页面空白』『闪退』)，都算有。\n"
    "2) 上下文 context：问题出在哪。"
    "学生指出了功能/操作/位置(如『登录功能』『点登录按钮时』『某个文件/某一行』『提交表单后』)，都算有；"
    "不要求一定给文件名或行号。\n"
    "3) 预期 expectation：本来想要什么结果。"
    "学生说了他期望发生什么(如『希望能登录成功』『应该显示列表』『想得到正确结果』)，就算有。\n\n"
    "判定原则：\n"
    "- 宁可鼓励、不要苛刻：学生只要给了某要素的具体信息（哪怕口语、不专业）就判 true；"
    "只有完全没提到、或纯空话(如『代码报错了』『帮我看看』)才判 false。\n"
    "- 只评价提问的清晰度与三要素，绝不替学生解决技术问题、绝不给代码答案。\n"
    "- 绝不臆断运行结果、绝不编造『正确答案』或『它会报某错』——你没有运行环境。\n"
    "- feedback 用中文、一两句、鼓励且具体：先肯定他写对的要素，再指出还缺哪个、怎么补；三要素齐全就明确肯定。\n"
    "- 只输出 JSON，键：phenomenon(bool), context(bool), expectation(bool), feedback(str), confidence(0~1 的小数)。"
    "不要输出 score（分数由系统按三要素计算）。\n\n"
    "判定示例（照这个宽松尺度）：\n"
    "· 『代码报错了』→ 现象F 上下文F 预期F（纯空话，什么都没说）\n"
    "· 『登录功能一直登不上去』→ 现象T(登不上去) 上下文T(登录功能) 预期F\n"
    "· 『我点登录按钮后页面没反应，希望能正常登录进去』→ 现象T(没反应) 上下文T(点登录按钮) 预期T(正常登录)\n"
    "· 『登录报 NullPointerException，在 UserService 第32行，期望完成登录』→ 现象T 上下文T 预期T"
)


def _score_from_factors(phenomenon: bool, context: bool, expectation: bool) -> int:
    """三要素 → 0~100 提问分（对齐 04 文档 §4.9：项数越多越高）。分值由系统定，不交给 LLM。"""
    n = sum([bool(phenomenon), bool(context), bool(expectation)])
    return {0: 12, 1: 40, 2: 66, 3: 92}[n]


def _fallback(prompt: str) -> dict:
    """LLM 不可用时的温和降级：用极轻量的本地启发式，给中性反馈，绝不崩。"""
    return {
        "phenomenon": False,
        "context": False,
        "expectation": False,
        "score": _score_from_factors(False, False, False),
        "feedback": "知返这会儿没连上，先自检一下：你的提问有没有说清【现象】（报了什么）、"
                    "【上下文】（哪段代码/哪一行）、【预期】（想要什么结果）这三样？补齐它们，AI 会更好帮你。",
        "confidence": 0.0,
        "degraded": True,
    }


def diagnose(scenario_id: str, prompt: str) -> dict:
    """诊断一条提问的三要素。永不抛出——LLM/解析失败一律走 fallback。"""
    prompt = (prompt or "").strip()
    if not prompt:
        return {
            "phenomenon": False, "context": False, "expectation": False,
            "score": 0,
            "feedback": "先写下你会怎么问 AI——哪怕一句话也行，知返再帮你看看缺什么。",
            "confidence": 1.0, "degraded": False,
        }

    scenario = SCENARIOS.get(scenario_id) or {"title": "调试求助", "brief": ""}
    if scenario_id == "custom" or not scenario.get("brief"):
        # 自带真实问题：没有预设背景，只能就学生这段文字本身判三要素
        scene_line = "场景：学生自带的真实问题（无预设背景，只就下面这段文字本身判断三要素）。"
    else:
        scene_line = f"场景：{scenario['title']}——{scenario['brief']}"
    user = (
        f"{scene_line}\n\n"
        f"学生写给 AI 的提问如下（只评价这段提问的三要素，不要回答这个技术问题）：\n"
        f"<<<\n{prompt}\n>>>"
    )
    try:
        resp = tutor.client.chat.completions.create(
            model=TUTOR_MODEL,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            temperature=0.2, max_tokens=400,
            response_format={"type": "json_object"},
        )
        raw = json.loads(resp.choices[0].message.content or "{}")
    except Exception:
        return _fallback(prompt)

    if not isinstance(raw, dict):
        return _fallback(prompt)

    phenomenon = bool(raw.get("phenomenon"))
    context = bool(raw.get("context"))
    expectation = bool(raw.get("expectation"))
    feedback = raw.get("feedback")
    if not isinstance(feedback, str) or not feedback.strip():
        feedback = "知返收到了你的提问。对照一下：现象、上下文、预期，这三样齐了吗？"
    try:
        confidence = float(raw.get("confidence", 0.7))
    except (TypeError, ValueError):
        confidence = 0.7
    confidence = max(0.0, min(1.0, confidence))

    return {
        "phenomenon": phenomenon,
        "context": context,
        "expectation": expectation,
        "score": _score_from_factors(phenomenon, context, expectation),  # 分由系统算，不信 LLM
        "feedback": feedback.strip(),
        "confidence": confidence,
        "degraded": False,
    }


# ---- P1-lite 资产化（doc12）：把诊断沉淀成 ExecutionEvent 事实日志。----
# 走 ExecutionEvent 而非 Event：它只 INSERT、永不调 apply_event，结构上就不进画像分。
# 命名空间隔离（source/合成session/kp=[]）保证对画像与成长轨迹双隐形。

def _summary(feedback: str) -> str:
    f = (feedback or "").strip().replace("\n", " ")
    return f[:80]


def log_diagnosis(db: Session, *, student_id: str, scenario_id: str, prompt: str, result: dict) -> ExecutionEvent | None:
    """把一次诊断沉淀为数字资产（ExecutionEvent）。student_id 为空则跳过（匿名不落库）。"""
    if not student_id:
        return None
    ev = ExecutionEvent(
        id=f"qt_{uuid.uuid4().hex[:16]}",
        version="v1",
        student_id=student_id,
        session_id=f"qtsess_{student_id}",   # 合成 id，不建 TutorSession → 对成长轨迹隐形
        pattern_id=QT_PATTERN_ID,            # 哨兵，提问训练无 pattern
        source=QT_SOURCE,                    # 独立来源，timeline 只认 run/submit
        kind=QT_KIND,                        # 非 RE/WA/HANG/OK
        error_family=None,
        knowledge_points=[],                 # 空 kp → 对画像掌握度隐形
        meta={
            "mode": "question_training",
            "scenario_id": scenario_id,
            "prompt": prompt,
            "phenomenon": bool(result.get("phenomenon")),
            "context": bool(result.get("context")),
            "expectation": bool(result.get("expectation")),
            "score": result.get("score"),
            "feedback_summary": _summary(result.get("feedback", "")),
            "confidence": result.get("confidence"),
            "degraded": bool(result.get("degraded")),
        },
        timestamp=now(),
    )
    db.add(ev)
    db.commit()
    return ev


# 三要素键 → 中文（短板展示用）
_FACTOR_ZH = {"phenomenon": "现象", "context": "上下文", "expectation": "预期"}
WEAKNESS_MIN_SAMPLES = 3  # doc11 闸门：样本不足不展示


def weakness_summary(db: Session, student_id: str, recent_n: int = 8) -> dict | None:
    """回放本人 qt_diagnose 资产，统计最近最常漏的要素（doc11/12 短板个性化的数据源）。
    degraded / confidence<0.7 记录事实但不参与统计；样本不足返回 None（不展示）。
    """
    if not student_id:
        return None
    rows = (db.query(ExecutionEvent)
            .filter_by(student_id=student_id, source=QT_SOURCE)
            .order_by(ExecutionEvent.timestamp.desc())
            .all())
    # 过滤：排除 degraded 和低置信（不参与短板统计）
    usable = []
    for r in rows:
        m = r.meta or {}
        if m.get("degraded"):
            continue
        c = m.get("confidence")
        if c is not None and c < CONFIDENCE_MIN:
            continue
        usable.append(m)
        if len(usable) >= recent_n:
            break
    if len(usable) < WEAKNESS_MIN_SAMPLES:
        return None
    # 数各要素被判 false 的次数
    miss = {k: sum(1 for m in usable if not m.get(k)) for k in _FACTOR_ZH}
    worst_key = max(miss, key=miss.get)
    if miss[worst_key] == 0:
        return None  # 三要素都常写到，无短板可提
    return {
        "factor": worst_key,
        "factor_zh": _FACTOR_ZH[worst_key],
        "miss_count": miss[worst_key],
        "sample_size": len(usable),
    }


# ---- P1-full 计分（doc12 / 04文档 §4.9）：把诊断结果记成 Prompt_Design 能力事件，进画像。----
# 走 event_engine.emit（confidence≥0.7 才进画像分，低置信入库不计分，沿用现有规则）。

def _today(ts: str) -> str:
    return (ts or "")[:10]   # ISO 时间戳取日期前缀 YYYY-MM-DD


def _today_positive_sum(db: Session, student_id: str) -> int:
    """今日已记的 Prompt_Design 正向 delta 合计（日上限用）。"""
    today = now()[:10]
    rows = (db.query(Event)
            .filter_by(student_id=student_id, capability="Prompt_Design")
            .all())
    return sum(e.delta for e in rows if e.delta > 0 and _today(e.timestamp) == today)


def _scored_same_prompt_today(db: Session, student_id: str, prompt: str) -> bool:
    """今日是否已对完全相同的提问记过正向分（防复制粘贴刷分）。"""
    today = now()[:10]
    rows = (db.query(Event)
            .filter_by(student_id=student_id, capability="Prompt_Design")
            .all())
    for e in rows:
        if e.delta > 0 and _today(e.timestamp) == today \
                and ((e.evidence or {}).get("refs") or {}).get("prompt") == prompt:
            return True
    return False


# 泛泛求代办（甩锅式收尾）：命中则计分降一档（doc12 C 档）。
_VAGUE_HANDOFF = ("帮我看看", "帮我看下", "帮我看一下", "帮看看", "看看哪", "看下哪",
                  "看一下哪", "看看怎么", "帮我改", "帮我弄", "帮我搞定", "怎么办", "咋办", "怎么弄")
# 明确协作请求：出现这类"请你判断/分析/解释/对比"的求助，不算泛泛求代办（避免误伤好提问）。
_CLEAR_COLLAB = ("判断", "分析", "解释", "说明", "对比", "比较", "是不是", "是否", "还是", "为什么", "原因")


def _is_vague_handoff(prompt: str) -> bool:
    p = (prompt or "")
    if not any(k in p for k in _VAGUE_HANDOFF):
        return False
    # 即便出现"帮我看看"，只要同时有明确协作请求（请你判断/分析/A还是B…），就不算泛泛
    if any(k in p for k in _CLEAR_COLLAB):
        return False
    return True


def score_diagnosis(db: Session, *, student_id: str, scenario_id: str, prompt: str, result: dict) -> Event | None:
    """P1-full：把一次诊断记成 Prompt_Design 能力事件（进画像）。返回事件或 None（未记分）。
    不记分的情况：匿名 / fallback降级 / 仅1要素(delta0) / 日上限已满 / 同句今日已记。
    """
    if not student_id or result.get("degraded"):
        return None
    prompt = (prompt or "").strip()
    if not prompt:
        return None

    n = sum([bool(result.get("phenomenon")), bool(result.get("context")), bool(result.get("expectation"))])
    delta = _DELTA_BY_FACTORS[n]
    if delta == 0:
        return None  # 1 个要素：不奖不罚，不产事件（emit 也拒绝 delta=0）

    # C 档：泛泛求代办（"帮我看看"且无明确协作请求）降一档。
    # 2要素本应 +1 → 降为 0 不记；0要素保持 -1；三要素完整不受影响（已是完整提问）。
    if _is_vague_handoff(prompt) and n == 2:
        return None

    if delta > 0:
        # 日上限：超过 +6 不再记正向；防同句复制粘贴刷分
        remaining = DAILY_POSITIVE_CAP - _today_positive_sum(db, student_id)
        if remaining <= 0:
            return None
        if _scored_same_prompt_today(db, student_id, prompt):
            return None
        delta = min(delta, remaining)
    # 负向（-1，纯"帮我看看"）不封顶（04文档 §5.5），照记

    present = [_FACTOR_ZH[k] for k in _FACTOR_ZH if result.get(k)]
    missing = [_FACTOR_ZH[k] for k in _FACTOR_ZH if not result.get(k)]
    summary = (f"提问三要素 {n}/3（有：{'、'.join(present) or '无'}；"
               f"缺：{'、'.join(missing) or '无'}）")
    try:
        return event_engine.emit(
            db,
            student_id=student_id,
            session_id=f"{QT_SESSION_PREFIX}{student_id}",
            capability="Prompt_Design",
            delta=delta,
            producer="llm_judge",
            confidence=float(result.get("confidence", 0.7)),
            evidence={
                "type": "prompt_diagnosis",
                "summary": summary,
                "refs": {"scenario_id": scenario_id, "prompt": prompt,
                         "factors": {k: bool(result.get(k)) for k in _FACTOR_ZH}},
            },
            context={"source_module": "question_training", "scenario_id": scenario_id},
        )
    except event_engine.EventRejected:
        return None
