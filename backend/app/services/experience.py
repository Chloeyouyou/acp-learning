"""学生经历记忆（三层记忆的第二层，借鉴土豆分支 branch-logic.ts）。

关卡内化结算时把「这个学生怎么踩坑、卡在哪、怎么走出来」确定性沉淀成一条经历
（不经 LLM——摘要由结构化事实拼成，天然不含 expected_fix，是落库端的泄题硬门控）；
新关卡里按相关度召回 top2 注入导师 prompt，让引导接得上个人历史。

检索算法移植自土豆分支：中文虚词过滤 + 一/二元语法覆盖率打分，按查询自身规模
归一化（长记忆不天然占优），低于 RELEVANCE_FLOOR 宁可空手也不带跑题记忆进 prompt。
"""

import re
import uuid

from sqlalchemy.orm import Session

from ..models import ExecutionEvent, SessionMessage, StudentExperience, TutorSession, now
from . import mine_engine

# ---------------- 纯逻辑：轻量检索（无向量库） ----------------

# 高频虚词：只靠它们撞上的不算相关。
_STOP_CHARS = set(
    "的了是我你他她它们呢吧吗啊哦嗯就都也很还在有和与或于对把被这那个么什怎不没"
    "自己一些如果但可能觉得知道现在时候东西事情"
)

_PUNCT_RE = re.compile(r"[\s，。！？、,.!?;；:：\"'“”‘’()（）《》\[\]【】—-]")
# ASCII 词（错误名/标识符）整词作 token——按字符切会让 IndexError 和
# ZeroDivisionError 靠 er/ro/or 这类碎片误判相关。
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}")


def _retrieval_grams(text: str) -> tuple[set, set, set]:
    """中文内容词的一元/二元字符组 + ASCII 整词 token；两个字都是虚词的二元组不进集合。"""
    lowered = (text or "").lower()
    tokens = set(_ASCII_TOKEN_RE.findall(lowered))
    chars = list(_PUNCT_RE.sub("", _ASCII_TOKEN_RE.sub(" ", lowered)))
    unigrams, bigrams = set(), set()
    for i, ch in enumerate(chars):
        if ch not in _STOP_CHARS:
            unigrams.add(ch)
        if i + 1 < len(chars) and not (ch in _STOP_CHARS and chars[i + 1] in _STOP_CHARS):
            bigrams.add(ch + chars[i + 1])
    return unigrams, bigrams, tokens


# 低于这个覆盖率视为不相关（与土豆分支同门槛，测试用真实题面校准过）。
RELEVANCE_FLOOR = 0.12


def relevance_score(query: str, doc: str) -> float:
    """检索相关度（0~1）：查询的内容词被经历覆盖的比例。二元组权重加倍（更具体），
    按查询自身规模归一化——长经历不天然占优。"""
    q_uni, q_bi, q_tok = _retrieval_grams(query)
    d_uni, d_bi, d_tok = _retrieval_grams(doc)
    total = len(q_uni) + (len(q_bi) + len(q_tok)) * 2
    if total == 0:
        return 0.0
    hit = (sum(1 for g in q_uni if g in d_uni)
           + sum(2 for g in q_bi if g in d_bi)
           + sum(2 for t in q_tok if t in d_tok))
    return hit / total


# ---------------- 结算时沉淀经历（确定性，不经 LLM） ----------------

_CATEGORY_ZH = {"boundary": "边界", "loop": "循环", "null": "空值", "arithmetic": "算术"}
_AXES_ZH = {"cause": "成因机制", "locate": "定位方法", "prevent": "预防策略"}


def _pattern_meta(session: TutorSession) -> dict:
    """题目元数据：优先题库（有 name/category/cognitive_root），生成题等取不到时回退 manifest。"""
    mine = session.manifest["mines"][0]
    try:
        p = mine_engine.get_pattern(session.pattern_id)
    except Exception:
        p = {}
    return {
        "name": p.get("name", session.pattern_id),
        "category": p.get("category", ""),
        "cognitive_root": p.get("cognitive_root", ""),
        "root_cause": mine.get("root_cause", ""),
        "knowledge_points": mine.get("knowledge_points", []),
        "symptom_sample": mine.get("symptom_sample", ""),
    }


def build_summary(session: TutorSession, meta: dict, error_families: list[str],
                  support_turns: int, axes: dict) -> tuple[str, list[str]]:
    """由结构化事实拼摘要 + 检索关键词。绝不引用 expected_fix / fix_check / buggy_code。"""
    cat_zh = _CATEGORY_ZH.get(meta["category"], meta["category"])
    fam_txt = "、".join(dict.fromkeys(error_families)) if error_families else "结果不符预期"
    struggle = f"中途卡壳 {support_turns} 次、" if support_turns else ""
    axes_zh = "、".join(_AXES_ZH[a] for a in ("cause", "locate", "prevent") if axes.get(a))
    student_turns = sum(1 for m in (session.history or []) if m.get("role") == "user")
    summary = (
        f"在《{meta['name']}》（{cat_zh}类）遇到 {fam_txt}，根因是{meta['root_cause']}"
        + (f"（当时的认知盲点：{meta['cognitive_root']}）" if meta["cognitive_root"] else "")
        + f"。全程 {student_turns} 轮对话、提示最深用到 {session.hint_level}，"
        + struggle + f"最后他自己说清了{axes_zh or '要点'}，完成内化。"
    )
    keywords = list(dict.fromkeys(
        [meta["name"], cat_zh, meta["category"]]
        + list(meta["knowledge_points"])
        + error_families
        + ([meta["symptom_sample"].splitlines()[0]] if meta["symptom_sample"] else [])
    ))
    return summary, [k for k in keywords if k]


def record_on_completion(db: Session, session: TutorSession) -> StudentExperience | None:
    """内化结算时沉淀一条经历（append-only，只 INSERT）。coop 会话不参与。"""
    if session.is_coop:
        return None
    meta = _pattern_meta(session)
    error_families = [
        e.error_family for e in db.query(ExecutionEvent)
        .filter_by(session_id=session.id).order_by(ExecutionEvent.timestamp)
        if e.error_family
    ]
    tutor_msgs = db.query(SessionMessage).filter_by(session_id=session.id, role="tutor").all()
    support_turns = sum(1 for m in tutor_msgs if (m.meta or {}).get("support_mode"))
    axes = dict(session.internalize_scores or {})
    summary, keywords = build_summary(session, meta, error_families, support_turns, axes)
    exp = StudentExperience(
        id=f"exp_{uuid.uuid4().hex[:12]}",
        student_id=session.student_id,
        session_id=session.id,
        pattern_id=session.pattern_id,
        summary=summary,
        keywords=keywords,
        facts={
            "error_families": error_families,
            "hint_level": session.hint_level,
            "support_turns": support_turns,
            "internalize_axes": axes,
            "category": meta["category"],
        },
        created_at=now(),
    )
    db.add(exp)
    return exp


# ---------------- 新关卡召回 ----------------

_RECALL_POOL = 50   # 每个学生只在最近 N 条里检索（够用且省查询）
RECALL_LIMIT = 2


def build_query(mine: dict, pattern: dict | None = None) -> str:
    """当前雷的检索查询词：根因 + 认知盲点 + 知识点 + 类别 + 症状。会话内固定。"""
    p = pattern or {}
    parts = [
        mine.get("root_cause", ""), p.get("cognitive_root", ""),
        " ".join(mine.get("knowledge_points", [])),
        _CATEGORY_ZH.get(p.get("category", ""), p.get("category", "")),
        mine.get("symptom_sample", ""),
    ]
    return " ".join(x for x in parts if x)


def recall(db: Session, student_id: str, query: str,
           exclude_pattern_id: str = "", limit: int = RECALL_LIMIT) -> list[StudentExperience]:
    """按相关度召回过门槛的 top 经历；排除当前题（变式迁移不剧透同题根因）。
    同分按时间倒序（新经历优先）。低于门槛宁可空手。"""
    q = db.query(StudentExperience).filter_by(student_id=student_id)
    if exclude_pattern_id:
        q = q.filter(StudentExperience.pattern_id != exclude_pattern_id)
    pool = q.order_by(StudentExperience.created_at.desc()).limit(_RECALL_POOL).all()
    scored = [
        (relevance_score(query, exp.summary + " " + " ".join(exp.keywords or [])), exp)
        for exp in pool
    ]
    scored = [(s, e) for s, e in scored if s >= RELEVANCE_FLOOR]
    # pool 已按时间倒序，稳定排序保证同分时新经历优先
    scored.sort(key=lambda t: t[0], reverse=True)
    return [e for _, e in scored[:limit]]
