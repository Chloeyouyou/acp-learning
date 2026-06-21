"""提问训练 P0（docs/design/12）。

只诊断「提问本身」的三要素完整度（现象 / 上下文 / 预期），给分 + 反馈。
P0 边界：不调 event_engine、不落 Prompt_Design、不动画像、不复用六阶段逻辑。
仅复用 LLM client（tutor.client / TUTOR_MODEL）。LLM 不可用时温和降级，绝不让页面崩。
"""

import json

from ..config import TUTOR_MODEL
from . import tutor

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
}

SYSTEM = (
    "你是「知返」，一个教初学者『把问题问清楚』的提问教练。"
    "你的唯一任务是诊断学生写给 AI 的【提问本身】好不好，而不是去回答这个技术问题。\n"
    "评判一个好提问是否包含三要素：\n"
    "1) 现象 phenomenon：报了什么错、看到什么实际表现（错误类型/具体现象）。\n"
    "2) 上下文 context：哪段代码、哪个文件、哪一行、什么场景。\n"
    "3) 预期 expectation：本来想要什么结果。\n\n"
    "严格规则：\n"
    "- 只评价提问的清晰度与三要素完整度，绝不替学生解决技术问题、绝不给代码答案。\n"
    "- 绝不臆断运行结果、绝不编造『正确答案』或『它会报某错』——你没有运行环境。\n"
    "- 三要素判断只看学生提问里【是否真的写出了】该要素，含糊带过不算。\n"
    "- feedback 用中文、一两句、鼓励且具体：指出缺哪个要素、怎么补；若三要素齐全就肯定他。\n"
    "- 只输出 JSON，键：phenomenon(bool), context(bool), expectation(bool), feedback(str), confidence(0~1 的小数)。"
    "不要输出 score（分数由系统按三要素计算）。"
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
    user = (
        f"场景：{scenario['title']}——{scenario['brief']}\n\n"
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
