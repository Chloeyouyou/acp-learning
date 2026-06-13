"""AI导师（02文档）。开卷引导：Ground Truth注入 + 状态机 + 引导阶梯 + 强类型事件输出。

LLM后端：DeepSeek（OpenAI兼容接口）。DeepSeek的json_object模式不做schema强制，
所以输出格式写进system prompt，返回后用Pydantic校验，校验失败重试一次。
"""

import os
import re
from typing import Literal, Optional

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from ..config import DEEPSEEK_BASE_URL, HINT_LEVELS, STAGES, TUTOR_MODEL
from ..models import Event, TutorSession
from . import event_engine, mine_engine, profile

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=DEEPSEEK_BASE_URL,
)


class TutorEvent(BaseModel):
    capability: Literal["Root_Cause_Reasoning", "Hypothesis_Testing",
                        "Independent_Debug", "AI_Verification"]
    delta: int = Field(ge=-3, le=3)
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(description="触发该事件的学生对话原文摘录")


class InternalizationScore(BaseModel):
    """⑥内化三轴判定（按整个⑥阶段对话累计，由LLM逐轮报告，系统累加）。"""
    cause: bool = False    # 成因机制说清了
    locate: bool = False   # 定位方法说清了
    prevent: bool = False  # 预防/迁移策略说清了


class TutorTurn(BaseModel):
    reply: str
    stage_transition: Optional[Literal["①发现", "②定位", "③归因", "④修复", "⑤验证", "⑥内化"]] = None
    hint_level_used: Literal["L0", "L1", "L2", "L3", "L4", "L5"]
    student_progressed: bool
    answer_begging: bool
    # ③归因专用：学生本轮发言回应的是哪一步。连续live实测DeepSeek对该字段的稳定语义就是
    # 「刚做完的那一步」，于是顺势设计：它 + student_progressed（答对/答错）共同驱动步进
    attribution_step: Optional[Literal["variable_trace", "rule_compare", "root_cause_expression"]] = None
    # ⑥内化专用：本轮过后三轴各自是否已达成（含此前轮次的累计）
    internalization: Optional[InternalizationScore] = None
    events: list[TutorEvent] = []


# ①发现的退出条件「能描述异常现象」不依赖LLM判断：消息里出现明确异常签名即规则判定达成。
# 每个错误家族一份「定位剧本」：meaning=报错在说什么，probe=定位提问方向，example=语气示范。
ERROR_PLAYBOOK = {
    r"IndexError|ArrayIndexOutOfBoundsException|StringIndexOutOfBoundsException": {
        "meaning": "程序访问了一个不存在的位置——下标超出了容器的实际范围",
        "probe": "哪一行在用下标访问、下标的值从哪来（循环边界？长度计算？）、容器此刻实际多长",
        "example": "好，这个报错已经给了我们方向。IndexError 通常说明程序访问了一个不存在的位置。"
                   "我们先不急着改代码，先定位：代码里哪一行在用下标访问列表？那个下标的值是从哪里来的？",
    },
    r"ZeroDivisionError|ArithmeticException": {
        "meaning": "程序在某一步把 0 当成了除数",
        "probe": "哪个表达式在做除法、除号右边的值是怎么算出来的、什么输入会让它变成 0（空列表？边界输入？）",
        "example": "好，问题已经很明确了：程序在某一步把 0 当成了除数。我们先找分母来自哪里。"
                   "代码里哪个表达式在做除法？除号右边的值是怎么计算出来的？",
    },
    r"NullPointerException|AttributeError.*NoneType|NoneType.*has no attribute": {
        "meaning": "程序在一个「空」对象上调用了方法或属性——那个变量此刻还什么都不是",
        "probe": "哪个变量是空的、它本应在哪一步被赋值或初始化、为什么那一步没有发生",
        "example": "好，这条信息很关键：有个对象在被使用的时候还是空的。先别动代码，先弄清楚："
                   "报错那一行用到了哪些变量？其中哪一个有可能从来没被赋过值？",
    },
    r"KeyError": {
        "meaning": "程序用一个字典里不存在的键去取值",
        "probe": "访问的键具体是什么、取值那一刻字典里实际有哪些键、这个键本应在哪里被写入",
        "example": "好，报错直接告诉了我们是哪个键找不到。先看两件事：这个键是从哪来的？"
                   "取值之前，字典里到底有没有它——你打算怎么确认？",
    },
    r"TypeError|ClassCastException": {
        "meaning": "某个操作拿到了它处理不了的类型——两边的类型对不上",
        "probe": "报错点的操作数/参数各是什么类型、那个意外的类型是哪一步产生的",
        "example": "好，报错说明有个操作收到了它处理不了的类型。先定位：报错那一行涉及哪些值？"
                   "你预期它们各是什么类型，实际呢？",
    },
    r"ValueError|NumberFormatException": {
        "meaning": "类型对了但值不合法——内容超出了函数能接受的范围或格式",
        "probe": "传进去的具体值是什么、合法的范围/格式是什么、这个值是从哪一步来的",
        "example": "好，这个报错说明传进去的值内容不合法。先看：出错那一步收到的具体值是什么？"
                   "它是从哪里算出来或读进来的？",
    },
    r"AttributeError|NameError": {
        "meaning": "程序访问了一个对象上不存在的属性，或一个没定义过的名字",
        "probe": "被访问的对象实际是什么、这个名字/属性在哪里定义的、拼写和定义时机对不对",
        "example": "好，报错告诉我们有个名字或属性找不到。先确认：报错那一行访问的对象，"
                   "运行到那里时它实际是什么？这个属性是在哪里定义的？",
    },
    r"Traceback \(most recent call last\)|Exception in thread": {
        "meaning": "完整的异常栈——它自底向上记录了出错时的调用路径",
        "probe": "栈最后一行的异常类型是什么、往上找最后一处自己写的代码在哪一行",
        "example": "好，你把完整的报错栈贴出来了，这很有用。我们从最后一行往上看："
                   "异常类型是什么？再往上数，最后一个属于你自己代码的位置是哪一行？",
    },
}


def detect_error_signature(text: str):
    """返回 (匹配到的异常签名原文, 该错误家族的定位剧本)，未命中返回 None。"""
    for pattern, playbook in ERROR_PLAYBOOK.items():
        m = re.search(pattern, text)
        if m:
            return m.group(0), playbook
    return None


# 规则跃迁当轮注入：导师人格层（Mentor Personality Layer）。
# 不靠禁令堆砌，靠固定的「承接→解读→提问」三步结构让重复询问现象自然失去位置。
MENTOR_LAYER_TEMPLATE = """

[本轮情境]
学生刚贴出了明确报错「{sig}」，系统已判定①发现达成，当前阶段就是②定位。
这条报错本身就是对现象的完整描述，现象确认这一步已经过去了——不需要再询问测试输入，直接开始定位。

[本轮回应方式]
像一位经验丰富的人类导师那样，自然的三步，全文2~4句话：
1. 承接：先接住学生的线索，让他知道这条报错有价值（一句即可，如「好，这个报错已经给了我们方向。」）
2. 解读：用一句话讲清这个报错在说什么——{meaning}。只解释报错的含义，不点出问题在哪一行
3. 提问：提出一个具体、自然的下一步问题，方向：{probe}。一次只推进一个主问题（后面可跟一个紧贴的小追问）

语气示范（参考其结构和口吻，结合本题代码自己组织语言，不要照抄）：
「{example}」"""


def mine_line_text(pattern_id: str) -> tuple[str, int] | None:
    """从模式库取出雷所在行的代码文本和行号（学生看到的就是这份buggy_code）。"""
    try:
        pattern = mine_engine.get_pattern(pattern_id)
        line_no = pattern["mine_location"]["line"]
        lines = pattern["buggy_code"].splitlines()
        if 1 <= line_no <= len(lines):
            return lines[line_no - 1].strip(), line_no
    except (KeyError, TypeError):
        pass
    return None


def message_points_at_mine(message: str, pattern_id: str) -> bool:
    """②定位的退出条件「指出可疑代码位置」规则判定：学生引用了雷行代码，或点名了雷所在行号。"""
    hit = mine_line_text(pattern_id)
    if not hit:
        return False
    line_text, line_no = hit
    norm = lambda s: re.sub(r"\s+", "", s)
    target = norm(line_text).rstrip(":")
    if target and target in norm(message):
        return True
    return bool(re.search(rf"第\s*{line_no}\s*行|line\s*{line_no}\b", message, re.IGNORECASE))


# ③归因的三步进度（存session.attribution_step，导师每轮只围绕当前步提问）
ATTRIBUTION_STEPS = ["variable_trace", "rule_compare", "root_cause_expression"]
ATTRIBUTION_STEP_ZH = {
    "variable_trace": "变量追踪（让学生代入具体输入，亲口说出关键变量当时的取值）",
    "rule_compare": "规则对照（让学生说出合法范围/预期规则，并和实际值对照）",
    "root_cause_expression": "根因表达（请学生用自己的话完整说一遍这个 Bug 为什么会发生）",
}

# ③归因阶段常驻注入：变量追踪 → 规则对照 → 根因表达，三步走完才放行④修复。
ATTRIBUTION_LAYER_TEMPLATE = """

[③归因引导剧本]
学生已经定位到可疑代码：`{mine_line}`。本阶段的目标是让他自己说清楚「为什么错」——不是改代码。归因分三步：
1. 变量追踪：让学生代入一个具体输入，亲口说出关键变量当时的取值（如「如果 arr 是 [1,2,3]，len(arr) 是多少？循环里 i 会依次取到哪些值？」）
2. 规则对照：让学生说出合法范围/预期规则，并和上一步的实际值对照（如「列表 [1,2,3] 的合法下标范围是多少？i 取到 3 的时候，arr[3] 存在吗？」）
3. 根因表达：请学生用自己的话完整说一遍这个 Bug 为什么会发生

[当前归因进度]（由系统记录，只前进不回退，你不要从头开始）
当前步：{step_zh}
本轮输出JSON中两个字段共同上报归因进度，系统据此推进（你不要自己跳步）：
- attribution_step：学生本轮发言是在回应哪一步（即你们刚刚在做的那一步），取值 variable_trace / rule_compare / root_cause_expression
- student_progressed：学生是否答对/完成了这一步的目标——答对填 true（系统推进到下一步，你的回复顺势提出下一步的问题）；答错、不完整或卡住填 false（你把这一步的问题拆得更小继续问，不要跳步也不要原句重发）
例：当前步是 variable_trace，学生正确说出「len 是 3，i 取 0,1,2,3」→ attribution_step 填 "variable_trace"，student_progressed 填 true，你的回复接着问合法下标范围

阶段放行判定（从严）：
- 仅当当前步是「根因表达」且学生的表述包含完整因果机制——什么值、违反了什么规则、所以为什么报错——并与 Ground Truth 根因语义一致，才在 stage_transition 填「④修复」
- 只指出位置或表面改法不算通过：学生若只说「因为 +1 错了」，attribution_step_completed 填 false，顺着他的话追问机制（「+1 为什么会导致越界？」），不要放行
- 判定根因达标并填「④修复」的同一轮，必须产出 Root_Cause_Reasoning 正向事件，evidence 引用学生说出根因的原话

引导方式：
- 每一步学生答对，先承接肯定（「很好」「对」），再顺着他刚说的内容问下一步；一次只问一个主问题
- 本阶段绝不给出修复代码或修改建议，也绝不替学生说出根因
- 本轮输出的JSON必须包含字段 attribution_step（步骤名字符串）"""


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
每轮回复前，先判断学生本轮发言是否已满足当前阶段的退出条件；满足就必须在stage_transition中填写下一阶段（每轮最多前进一个阶段）：
①发现：学生能描述异常现象（如复述了报错信息）→ 填"②定位"
②定位：学生指出可疑代码位置（与Ground Truth位置一致）→ 填"③归因"
③归因：学生用自己的话说出包含完整因果机制的原因（什么值→违反什么规则→为何报错），且与根因语义一致；只指出位置或表面改法（如"+1错了"）不算 → 填"④修复"
④修复：学生表示已修改代码（实际判定由系统测试完成，你只评价方向）→ 保持④等待提交
⑤验证：学生至少完成一个边界测试的完整解释（输入、预期结果、为什么）→ 填"⑥内化"；只说"都能过/没问题"不算
⑥由系统驱动，你不主动跳转
注意：学生一轮发言可能同时满足多级条件（如同时说出位置和原因），也只前进一个阶段，下一轮再判断。

[行为红线]
1. 任何阶段不输出修改后的代码或表达式——哪怕学生已经说对了原因，也不要替他写出改法（如不要说"改成range(len(arr))"），让他自己写出来并提交（L5也只讲思路）
2. 在确认学生猜测对错之前，先要求说理由（"你为什么这么认为？"）
3. 不泄露雷清单的存在——学生视角里Bug是代码本来就有的
4. 学生直接索要答案：拒绝，降回提问，并将answer_begging标记为true
5. 学生情绪挫败时先共情降难度，再回到引导

[表达风格]
你是引导型导师，不是答题模板。每轮回复先承接学生这一轮说了什么（接住他的线索或情绪），再往前推一步；通常2~4句话，一次只聚焦一个主问题。
回复前看一眼对话历史：不要重复你上一轮已经问过的问题。如果学生没接住你上轮的问题，就把它拆小、换一个更具体的切口重新问，而不是原句重发。
深入浅出：讲到抽象概念（下标、越界、None、循环次数…）时，尽量配一个生活化的小类比或一个具体的小例子，帮零基础学生建立直觉，别堆术语。

[升级规则]
同级停留≥3轮无实质进展、学生明确说"不知道/卡住了" → 提示级别升1级

[事件规范]
只允许产出这4类能力事件，且必须引用学生对话原文作为evidence：
- Root_Cause_Reasoning：学生归因表述与根因语义一致（首次一致+3，confidence≥0.8才报）
- Hypothesis_Testing：学生主动提出可检验假设（+1）或动手构造输入验证（+2）
- Independent_Debug：仅报负向（盲改碰运气-1）；正向由系统规则结算，你不报
- AI_Verification：学生主动验证你的说法（运行/查文档对照，+3）
没有把握的事件宁可不报。

[输出格式]
你的每轮回复必须是一个合法的JSON对象，不含任何JSON以外的文字，结构如下：
{{
  "reply": "给学生的回复文字",
  "stage_transition": null,            // 学生达到当前阶段退出条件时填下一阶段（如"③归因"），否则null
  "hint_level_used": "L1",             // 本轮实际使用的提示级别 L0-L5
  "student_progressed": true,          // 本轮学生是否有实质进展
  "answer_begging": false,             // 学生本轮是否在直接索要答案
  "attribution_step": null,            // 仅③归因阶段必填：学生本轮回应的归因步（variable_trace/rule_compare/root_cause_expression），其他阶段null
  "internalization": null,             // 仅⑥内化阶段必填：{{"cause": bool, "locate": bool, "prevent": bool}}（按⑥阶段对话累计判断），其他阶段null
  "events": [                          // 本轮观测到的能力事件，无则为空数组
    {{"capability": "Hypothesis_Testing", "delta": 1, "confidence": 0.85, "evidence": "学生原文摘录"}}
  ]
}}"""


# 学生提交失败后由 main.py 包装成这个开头的消息回流到对话，④剧本里有对应的反馈策略
FIX_FAILED_PREFIX = "（我提交了修复，但测试未通过）"


def diagnose_failed_fix(pattern_id: str, code: str) -> str:
    """失败提交的规则诊断：雷行没动 vs 动了但不对。给导师做针对性引导的抓手。"""
    hit = mine_line_text(pattern_id)
    if hit:
        line_text, line_no = hit
        if re.sub(r"\s+", "", line_text) in re.sub(r"\s+", "", code):
            return f"雷行未被修改：出问题的第{line_no}行 `{line_text}` 在提交代码中原样保留"
        return "雷行已被修改，但新写法仍未通过修复检查"
    return "未通过修复检查"


# ④修复阶段常驻注入：学生自己提思路、自己改代码；失败反馈针对诊断引导，不复读「测试失败」。
REPAIR_LAYER_TEMPLATE = """

[④修复引导剧本]
学生已经说清了根因。本阶段目标：学生自己提出修复思路、自己动手改代码、点「提交修复」按钮提交，由系统测试判定。你的职责：
- 先让学生说出修复思路：打算改哪一行、怎么改、为什么这样改能消除③里说清的根因
- 只评价方向，不给写法：方向对 → 肯定，并让他动手修改代码后提交；方向错 → 用③的结论反问（如「按这个改法，i 最大会取到几？」），让他自己发现
- 行为红线依旧：哪怕学生思路完全正确，也不要写出修改后的代码或表达式

[修复失败的反馈方式]
学生消息若以「{fix_failed_prefix}」开头，说明他刚提交了代码但系统测试未通过，消息里附有他提交的代码和[系统诊断]。此时：
1. 先承接：肯定他动手尝试了，别让挫败感累积
2. 针对[系统诊断]做具体引导，不要只说「测试失败了再想想」：
   - 「雷行未被修改」→ 他可能改错了地方：带他回想③的结论——问题出在哪一行？他刚才改动的又是哪一行？
   - 「雷行已被修改，但新写法仍未通过」→ 让他把新写法代入③里用过的具体输入，重新追踪一遍变量值，看看当初的越界/异常是否真的消失
3. 失败反馈同样不说出应该改成什么——即使学生此前已经说对了思路，也只提醒他「对照你自己说过的思路检查实际改动」，让他自己发现落差。
   能用 L3 以下的提问解决就不要用 L4/L5 的直给（提示级别越高，他的独立调试分越低）"""


# ⑤验证：按Bug模式类型推荐边界测试方向（02文档：训练边界测试意识）
BOUNDARY_TEST_SUGGESTIONS = {
    "boundary": "空列表 []、单元素列表 [5]、多元素典型列表 [1,2,3]",
    "loop": "让循环走0次的空输入、恰好走1次的输入、典型多步输入",
    "null": "None、正常对象、缺字段/缺键的对象",
    "arithmetic": "空列表、正常列表、会让分母趋零的极端值",
}
DEFAULT_BOUNDARY_SUGGESTION = "最小输入（空/零/None）、恰好卡在边界的输入、典型正常输入"


# ⑤验证阶段常驻注入：通过当前测试≠修复稳健，训练边界测试意识，走完一个边界解释才放行⑥。
VERIFY_LAYER_TEMPLATE = """

[⑤验证引导剧本]
学生的修复已通过系统测试，雷已排除。但通过当前测试不代表修复稳健——本阶段目标：训练学生的边界测试意识，不要直接结束。
该Bug模式（{category}类）值得验证的边界方向（你最多推荐2~3个，更优先让学生自己想）：{boundary_suggestions}

引导方式：
- 先问开放问题，让学生自己提：「你觉得还应该测哪些边界情况？」「这个修复会不会影响正常输入？」
- 学生提出合理的边界输入 → 承接肯定，让他说出预期结果并亲自跑一遍；你不要替他断言「这些测试一定能过」
- 学生只说「已经通过了/没问题了」 → 追问：「通过当前测试不代表修复稳健，我们再想一个边界输入——比如最小的输入会是什么？」
- 学生想不出来 → 从上面方向里挑一个最简单的起头（如「空列表传进去会发生什么？」），结果仍让他自己推演

事件规范（本阶段重点观测 Hypothesis_Testing）：
- 学生主动提出可检验的边界输入（说清测什么）→ Hypothesis_Testing +1
- 学生构造输入并解释了预期结果/推演了变量值 → Hypothesis_Testing +2

阶段放行（从严）：
- 学生至少完成一个边界测试的完整解释（输入是什么、预期结果是什么、为什么）后，才在 stage_transition 填「⑥内化」
- 只口头说「都能过/没问题」不算完成，不要放行

内化问题（进入⑥后系统会用，本阶段可顺带预热一个）：
{internalize_questions}
「已内化」的判定在⑥内化阶段进行，本阶段你不要宣布学生已内化"""


# ⑤验证的退出条件规则判定：消息同时说出「具体边界输入」和「预期结果」即完整解释
BOUNDARY_INPUT_RE = re.compile(
    r"空列表|空数组|空字符串|空输入|空的|\[\s*\]|None|null|单元素|一个元素|只有一个|"
    r"\[\s*-?\d+\s*\]|0\s*个|零个|边界值|最大值|最小值")
EXPECT_RE = re.compile(
    r"预期|应该(返回|是|得到|输出)|会(返回|得到|输出|是)|结果(是|应该|为)|返回\s*\S|输出\s*\S")


def message_explains_boundary_test(message: str) -> bool:
    return bool(BOUNDARY_INPUT_RE.search(message)) and bool(EXPECT_RE.search(message))


# 纯表态（我懂了/会了/以后注意）不携带任何机制信息，规则层直接拦截，不交给LLM判
ACK_ONLY_RE = re.compile(
    r"^[\s，。,.!！~～]*(我?(懂|会|明白|知道|清楚|理解)了?|好的?|嗯+|哦+|ok|OK|行|"
    r"以后(我?会?)?注意点?|没问题|学到了)+[\s，。,.!！~～]*$")


def is_substantive(message: str) -> bool:
    """⑥内化的发言是否可能携带具体机制/方法——太短或纯表态一律不算。"""
    msg = message.strip()
    return len(msg) >= 12 and not ACK_ONLY_RE.match(msg)


# ⑥内化阶段常驻注入：复述 + 迁移，三轴评分≥2才通过，知识点「已解决」→「已内化」。
INTERNALIZE_LAYER_TEMPLATE = """

[⑥内化引导剧本]
学生已完成修复并通过了边界验证。本阶段目标：复述 + 迁移——他要用自己的话把这个Bug讲清楚，知识点才能从「已解决」升级为「已内化」。
开场（进入本阶段的第一轮）：先肯定他完成了验证，然后从下面的内化问题里挑1~2个开始提问：
{internalize_questions}
要分轮问齐三个维度（一次只问一个）：
a. 成因：这个 Bug 为什么会发生？（要求说出具体机制）
b. 定位：你当时是怎么定位到它的？（报错信息→可疑行→变量追踪的路径）
c. 迁移：下次看到类似错误，你会先检查什么？

[内化评分]（每轮在输出JSON的 internalization 字段报告，按整个⑥阶段对话**累计**判断）
- cause：学生是否已说清成因机制
- locate：学生是否已说清定位方法
- prevent：学生是否已说清预防/迁移检查点
例：学生此前已说清成因，本轮又讲了定位方法 → {{"cause": true, "locate": true, "prevent": false}}
判定从严：「我懂了/会了/以后注意」这类表态一律不算（系统也会规则拦截）；必须包含具体机制、具体路径或具体检查点。
系统规则：≥2轴为true即内化通过，系统会自动升级知识点并结束会话，你不要自行宣布。

[未通过时的引导]
- 不要说「错了」：先承接他说对的部分，点名还缺哪个维度，换一种问法让他补
  （如成因说不清 → 「用 [1,2,3] 这个输入，把出错过程再走一遍？」；迁移说不清 → 「下次报这个错，你第一眼看代码的什么地方？」）
- 绝不替学生总结完整答案——他说不出来就把问题拆小{variant_note}"""

VARIANT_NOTE = """
- 该模式配有变式题库（variant_pool）：你可以预告「下一版会用相似的Bug检查你的迁移能力」，但本版不出变式题"""


# 受挫检测（规则层）：学生卡住/答错/想放弃的信号，命中即触发「止损共情层」。
# 用负向先行断言避开常见误伤：「会不会」「知不知道」不算受挫。
FRUSTRATION_RE = re.compile(
    r"(?<!会)不会(?!不)|(?<!知)不知道|不懂|看不懂|不明白|没思路|没头绪|没想法|想不出|想不到|毫无头绪|"
    r"太难|好难|有点难|难度|完全不|一点都不|"
    r"不行了|我不行|做不出|做不到|搞不定|"
    r"放弃|算了|不想做|懒得|不做了|"
    r"好烦|烦死|累了|好累|晕|头晕|崩溃|焦虑|想哭|哭|"
    r"帮帮我|帮我一下|给点提示|给个提示|提示一下|"
    r"\?{3,}|？{3,}|啊啊+|唉+")

# 「卡住/卡了/死循环」是描述程序的高频词（尤其 loop/HANG 类题），不能一律当学生受挫
STUCK_RE = re.compile(r"卡住|卡了|卡死|卡在|卡壳")
PROGRAM_HANG_CTX = re.compile(r"程序|代码|循环|运行|死循环|输出|跑|一直|结束|停不|countdown|while|for")


def detect_frustration(message: str) -> bool:
    msg = message or ""
    if FRUSTRATION_RE.search(msg):
        return True
    # 「卡住」仅当不是在描述程序卡死时，才算学生本人受挫
    if STUCK_RE.search(msg) and not PROGRAM_HANG_CTX.search(msg):
        return True
    return False


# 各 Bug 类型的生活化类比，受挫时优先喂给导师把概念讲软
ANALOGY_HINTS = {
    "boundary": "数组下标越界，就像去一个只有 3 个人的队伍里点名「第 4 个人」——根本没这个人。3 个元素的合法编号是 0、1、2。",
    "loop": "循环多走一步，就像要上 3 级台阶却抬了 4 次脚，最后一步踏空。",
    "null": "在 None 上取属性，就像对着一个空盒子说「把里面的东西拿给我」——盒子里什么都没有。",
    "arithmetic": "除以零，就像把 5 个苹果分给 0 个人——「每人分几个」这个问题根本没有答案。",
}
DEFAULT_ANALOGY = "把抽象的报错换成一个身边的具体小例子，帮他建立直觉。"


# 止损共情层：检测到学生受挫时注入。降难度、共情、用类比讲软；到 L5 启用「托底」。
SUPPORT_LAYER_TEMPLATE = """

[学生似乎卡住了——切到「扶一把」模式]
这一轮学生表现出受挫或卡顿（答不出、说不会、想放弃）。请像一位有耐心的人类老师那样及时止损，别再端着「我不能告诉你答案」把他越逼越紧：
1. 先共情、卸压力：用一句话接住他的情绪（「没关系，这一步确实容易绕」「别急，我们慢一点」），不要说教。
2. 主动降难度：把当前问题换成一个更小、更具体的版本——给一个具体小输入（如 arr=[1,2,3]），只让他回答其中一个很小的点，而不是宏观提问。
3. 用生活化类比把概念讲软（可参考、自行组织）：{analogy}
4. 仍然不直接写出本题的修复代码或答案——你是把台阶降低，不是替他走完。{floor_note}"""

SUPPORT_FLOOR_NOTE = """
5. 已到最高提示级 L5、学生仍卡死：启用「托底」——换一个与本题无关的超简单小例子，把背后的原理完整讲透（这个例子可以讲清楚，因为它不是本题答案），讲完再请他把同样的道理用回自己的代码。宁可慢，也别让他彻底卡死、丧失信心。"""


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


def _call_llm(system: str, history: list[dict]) -> TutorTurn:
    messages = [{"role": "system", "content": system}] + history
    last_err = None
    for _ in range(2):  # schema校验失败重试一次
        resp = client.chat.completions.create(
            model=TUTOR_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=2048,
        )
        raw = resp.choices[0].message.content
        try:
            return TutorTurn.model_validate_json(raw)
        except ValidationError as e:
            last_err = e
            messages = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": (
                    f"（系统格式纠错，学生看不到这条消息）你的JSON不符合约定格式：{e}。"
                    "请严格按[输出格式]重新输出。注意：reply字段是给学生的，"
                    "内容只回应学生的上一条消息，绝不要提及格式问题或道歉。")},
            ]
    raise RuntimeError(f"导师输出格式校验失败: {last_err}")


def run_turn(db: Session, session: TutorSession, student_message: str) -> dict:
    """一轮对话：调LLM → 应用状态跃迁 → 落库LLM事件与规则事件。"""
    history = list(session.history) + [{"role": "user", "content": student_message}]

    # 规则跃迁层：退出条件可确定性判定的阶段不等LLM——①贴出异常签名、②指认雷行、⑤完整解释边界测试
    auto_advanced = None    # ①→②：消息含明确异常签名
    auto_located = False    # ②→③：消息引用雷行代码或点名行号
    auto_verified = False   # ⑤→⑥：消息同时说出边界输入和预期结果
    if session.stage == "①发现":
        hit = detect_error_signature(student_message)
        if hit:
            auto_advanced = hit
            session.stage = "②定位"
    elif session.stage == "②定位" and message_points_at_mine(student_message, session.pattern_id):
        auto_located = True
        session.stage = "③归因"
        session.attribution_step = "variable_trace"
    elif session.stage == "⑤验证" and message_explains_boundary_test(student_message):
        auto_verified = True
        session.stage = "⑥内化"
    rule_advanced = bool(auto_advanced) or auto_located or auto_verified

    # 止损共情层：检测受挫（明说不会/想放弃，或连续≥2轮无进展）→ 主动降难+共情+类比。
    # 规则层先把提示级别升一格，确保台阶真的降下来，不只靠 LLM 自觉（刚跃迁的当轮不触发）。
    frustrated = detect_frustration(student_message)
    support_mode = not rule_advanced and (frustrated or session.stalled_turns >= 2)
    if support_mode and HINT_LEVELS.index(session.hint_level) < len(HINT_LEVELS) - 1:
        session.hint_level = HINT_LEVELS[HINT_LEVELS.index(session.hint_level) + 1]

    system = build_system(session)
    if auto_advanced:
        sig, playbook = auto_advanced
        system += MENTOR_LAYER_TEMPLATE.format(sig=sig, **playbook)
    if session.stage == "③归因":
        if not session.attribution_step:  # 兼容旧会话/LLM路径进③
            session.attribution_step = "variable_trace"
        hit = mine_line_text(session.pattern_id)
        mine_line = hit[0] if hit else str(session.manifest["mines"][0]["location"])
        system += ATTRIBUTION_LAYER_TEMPLATE.format(
            mine_line=mine_line, step_zh=ATTRIBUTION_STEP_ZH[session.attribution_step])
    elif session.stage == "④修复":
        system += REPAIR_LAYER_TEMPLATE.format(fix_failed_prefix=FIX_FAILED_PREFIX)
    elif session.stage == "⑤验证":
        qs = "\n".join(f"- {q}" for q in session.manifest["mines"][0]["internalize_questions"])
        category = mine_engine.get_pattern(session.pattern_id)["category"]
        system += VERIFY_LAYER_TEMPLATE.format(
            category=category,
            boundary_suggestions=BOUNDARY_TEST_SUGGESTIONS.get(category, DEFAULT_BOUNDARY_SUGGESTION),
            internalize_questions=qs)
    elif session.stage == "⑥内化":
        mine0 = session.manifest["mines"][0]
        qs = "\n".join(f"- {q}" for q in mine0["internalize_questions"])
        system += INTERNALIZE_LAYER_TEMPLATE.format(
            internalize_questions=qs,
            variant_note=VARIANT_NOTE if mine0.get("variant_pool") else "")

    # 止损层叠加在阶段剧本之上（任何阶段受挫都适用）
    if support_mode:
        category = mine_engine.get_pattern(session.pattern_id)["category"]
        floor = SUPPORT_FLOOR_NOTE if session.hint_level == "L5" else ""
        system += SUPPORT_LAYER_TEMPLATE.format(
            analogy=ANALOGY_HINTS.get(category, DEFAULT_ANALOGY), floor_note=floor)

    turn = _call_llm(system, history)

    mine = session.manifest["mines"][0]

    # 状态更新
    session.history = history + [{"role": "assistant", "content": turn.reply}]
    session.stalled_turns = 0 if turn.student_progressed else session.stalled_turns + 1
    if HINT_LEVELS.index(turn.hint_level_used) > HINT_LEVELS.index(session.hint_level):
        session.hint_level = turn.hint_level_used

    # 模型可能返回跳级目标（学生一轮满足多级条件），按设计钳制为每轮最多前进一级；
    # 本轮已发生规则跃迁时忽略LLM跃迁，下一阶段是否达成留到下一轮判断
    stage_before_llm = session.stage
    step_before_llm = session.attribution_step

    # ③归因步进（只前进不回退，每轮最多一步）：
    # 学生答对了当前步（attribution_step==当前步 且 student_progressed），
    # 或模型已在回应更后面的步（addressed>当前步，钳制一格），都推进一步。
    # 刚进③的当轮（rule_advanced）不步进——学生此轮只是完成了定位，变量追踪还没开始
    if (stage_before_llm == "③归因" and not rule_advanced
            and turn.attribution_step in ATTRIBUTION_STEPS
            and step_before_llm in ATTRIBUTION_STEPS):
        cur = ATTRIBUTION_STEPS.index(step_before_llm)
        addressed = ATTRIBUTION_STEPS.index(turn.attribution_step)
        if (addressed == cur and turn.student_progressed and cur < len(ATTRIBUTION_STEPS) - 1) \
                or addressed > cur:
            session.attribution_step = ATTRIBUTION_STEPS[cur + 1]

    allow_transition = (turn.stage_transition and not rule_advanced
                        and STAGES.index(turn.stage_transition) > STAGES.index(session.stage))
    # ④修复放行门控：必须已走到「根因表达」步，前两步没走完时LLM的放行无效
    if allow_transition and stage_before_llm == "③归因" and step_before_llm != "root_cause_expression":
        allow_transition = False
    # ⑥内化放行门控：事件流为事实源——本会话至少有一条Hypothesis_Testing正向事件
    # （本轮申报的也算），否则学生还没完成任何边界测试，不得离开⑤验证
    if allow_transition and stage_before_llm == "⑤验证":
        has_hypothesis = any(
            e.capability == "Hypothesis_Testing" and e.delta > 0 for e in turn.events
        ) or db.query(Event).filter_by(
            session_id=session.id, capability="Hypothesis_Testing"
        ).filter(Event.delta > 0).count() > 0
        if not has_hypothesis:
            allow_transition = False
    if allow_transition:
        session.stage = STAGES[STAGES.index(session.stage) + 1]
        if session.stage == "③归因" and not session.attribution_step:
            session.attribution_step = "variable_trace"

    # ②定位达成（规则跃迁或LLM判定皆同）= 雷 planted→found
    if STAGES.index(session.stage) >= STAGES.index("③归因") and session.mine_status == "planted":
        session.mine_status = "found"
        if mine["pattern_id"].startswith("BP-BOUNDARY"):
            event_engine.on_boundary_located(
                db, student_id=session.student_id, session_id=session.id,
                mine=mine, hint_level=session.hint_level)

    # ⑤→⑥规则跃迁达成 = 边界测试完整解释，规则产出Hypothesis_Testing（同轮LLM报的HT去重）
    if auto_verified:
        event_engine.emit(
            db, student_id=session.student_id, session_id=session.id,
            capability="Hypothesis_Testing", delta=2, producer="rule",
            evidence={"type": "dialogue",
                      "summary": f"完整解释边界测试（输入+预期）：{student_message[:120]}"},
            context={"stage": "⑤验证", "mine_id": mine["mine_id"]})
        turn.events = [e for e in turn.events if e.capability != "Hypothesis_Testing"]

    # ③→④放行 = 根因表达达标，必须留下Root_Cause_Reasoning事件；LLM漏报时系统补记
    if (stage_before_llm == "③归因" and session.stage == "④修复"
            and not any(e.capability == "Root_Cause_Reasoning" for e in turn.events)):
        turn.events.append(TutorEvent(
            capability="Root_Cause_Reasoning", delta=3, confidence=0.8,
            evidence=student_message[:200]))

    # ⑥内化结算：LLM报告三轴累计判定，规则层先拦截纯表态（「我懂了」不携带机制信息）；
    # ≥2轴true → Internalization规则事件 + 知识点「已内化」+ 会话completed
    # （刚进⑥的当轮不评分——学生此轮只是完成了验证，复述还没开始）
    if (stage_before_llm == "⑥内化" and not rule_advanced and turn.internalization is not None
            and session.mine_status != "internalized" and is_substantive(student_message)):
        acc = dict(session.internalize_scores or {})
        for axis in ("cause", "locate", "prevent"):
            if getattr(turn.internalization, axis):
                acc[axis] = True
        session.internalize_scores = acc
        if sum(1 for v in acc.values() if v) >= 2:
            session.mine_status = "internalized"
            session.status = "completed"
            event_engine.on_internalized(
                db, student_id=session.student_id, session_id=session.id,
                mine=mine, axes=acc)
            profile.update_knowledge_state(
                db, student_id=session.student_id, pattern_id=session.pattern_id,
                knowledge_points=mine["knowledge_points"], new_state="已内化")

    # 规则事件：索要答案扣分。但受挫情境下的求助是「求助」不是「耍赖」，豁免扣分——
    # 共情止损与扣分惩罚不应同时发生（导师此轮已切到扶一把模式）。
    if turn.answer_begging and not support_mode:
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
        "stage_transition_raw": turn.stage_transition,
        "auto_advanced_by": auto_advanced[0] if auto_advanced else None,
        "auto_located": auto_located,
        "auto_verified": auto_verified,
        "attribution_step": session.attribution_step or None,
        "internalize_scores": session.internalize_scores or None,
        "session_status": session.status,
        "hint_level": session.hint_level,
        "support_mode": support_mode,
        "events_emitted": [e.capability for e in turn.events],
    }
