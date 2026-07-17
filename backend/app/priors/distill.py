"""蒸馏：把一条新证据并进先验档案。LLM 只负责语义判断（支持/矛盾/新观察），
晋升、退休、去重、临时态隔离全是确定性规则——三条硬门槛不押在模型自觉上：

- 3 证据门槛：候选须有 ≥3 个不同 source_id 的证据才晋升 active（样本量 2 的
  人格判断比没有更糟）；
- 临时态隔离：标了 transient 的观察进临时区、带 TTL、永不参与固化
  （「今天很累」不许变成「不喜欢复杂解释」）；
- 反例退休：active 先验累计 2 次矛盾 → retired（留档不删，人可查）。

失败关闭：LLM 挂了/输出垃圾 → 原样返回，绝不让蒸馏拖垮宿主主流程。
"""

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from .store import Evidence, utcnow_iso

PROMOTE_MIN_SOURCES = 3
RETIRE_CONTRADICTIONS = 2
TRANSIENT_TTL_HOURS = 48
MAX_CANDIDATES = 20      # 候选区封顶，最旧的先淘汰——防档案无限膨胀
MAX_STATEMENT_LEN = 120  # 超长陈述通常是模型在复述细节而非提炼倾向，直接拒收
_EVIDENCE_EXCERPT = 120  # 证据存 source_id 指针 + 短摘录，摘录只为人工审看

PROMPT_TEMPLATE = """你在维护一个学生的「思维默认值」档案：记录他通常怎样理解问题、怎样求助、怎样行动的长期倾向。

已有观察（带编号）：
{existing}

新证据（来自他刚完成的一次学习经历）：
{evidence}

请判断新证据说明了什么，输出 JSON：{{"decisions": [...]}}，每个 decision 是以下之一：
- {{"action": "support", "id": "<编号>"}} —— 新证据支持某条已有观察
- {{"action": "contradict", "id": "<编号>"}} —— 新证据与某条已有观察相反
- {{"action": "new", "statement": "<一句话>", "temporality": "durable"}} —— 值得长期观察的新倾向
- {{"action": "new", "statement": "<一句话>", "temporality": "transient"}} —— 只是当天状态（累/急/赶时间），不是长期倾向

硬规则：
1. 只总结思维方式、求助方式、理解方式的倾向；绝不写任何题目的具体解法、修复代码或答案线索。
2. statement 用第三人称一句话（如「遇到报错时他通常先改代码再读报错信息」），不超过 60 字，带「通常/倾向于」这类不确定措辞。
3. 情绪化、时间性的表现（今天状态差、这次在赶时间）一律标 transient。
4. 一次经历通常最多支撑 1-2 个 decision；没有值得记录的就输出 {{"decisions": []}}。"""


def build_prompt(data: dict, evidence: Evidence) -> str:
    items = data.get("candidates", []) + [
        p for p in data.get("priors", []) if p.get("status") == "active"
    ]
    existing = "\n".join(f"- [{p['id']}] {p['statement']}" for p in items) or "（还没有任何观察）"
    return PROMPT_TEMPLATE.format(existing=existing, evidence=evidence.text)


def _parse_decisions(raw: str) -> list[dict]:
    text = re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.M).strip()
    obj = json.loads(text)
    decisions = obj.get("decisions", [])
    return decisions if isinstance(decisions, list) else []


def _find(data: dict, item_id: str):
    for pool in ("candidates", "priors"):
        for p in data[pool]:
            if p.get("id") == item_id:
                return pool, p
    return None, None


def _distinct_sources(item: dict) -> int:
    return len({e.get("source_id") for e in item.get("evidence", [])})


def _support(data: dict, item_id: str, evidence: Evidence) -> None:
    pool, item = _find(data, item_id)
    if item is None or item.get("status") == "retired":
        return
    if any(e.get("source_id") == evidence.source_id for e in item["evidence"]):
        return  # 同一来源不重复计数——3 证据门槛必须是 3 次独立场景
    item["evidence"].append({
        "source_id": evidence.source_id, "at": evidence.at,
        "excerpt": evidence.text[:_EVIDENCE_EXCERPT],
    })
    item["updated_at"] = utcnow_iso()
    if pool == "candidates" and _distinct_sources(item) >= PROMOTE_MIN_SOURCES:
        data["candidates"].remove(item)
        item["status"] = "active"
        data["priors"].append(item)


def _contradict(data: dict, item_id: str, evidence: Evidence) -> None:
    pool, item = _find(data, item_id)
    if item is None or item.get("status") == "retired":
        return
    if any(c.get("source_id") == evidence.source_id for c in item["contradictions"]):
        return
    item["contradictions"].append({
        "source_id": evidence.source_id, "at": evidence.at,
        "excerpt": evidence.text[:_EVIDENCE_EXCERPT],
    })
    item["updated_at"] = utcnow_iso()
    if len(item["contradictions"]) >= RETIRE_CONTRADICTIONS:
        if pool == "priors":
            item["status"] = "retired"   # 留档可查，不注入
        else:
            data["candidates"].remove(item)  # 候选还没立住就被打脸，直接出局


def _new_observation(data: dict, statement: str, temporality: str, evidence: Evidence) -> None:
    statement = (statement or "").strip()
    if not statement or len(statement) > MAX_STATEMENT_LEN:
        return
    if temporality == "transient":
        expires = (datetime.now(timezone.utc)
                   + timedelta(hours=TRANSIENT_TTL_HOURS)).isoformat(timespec="seconds")
        for t in data["transient"]:
            if t.get("statement") == statement:
                t["expires_at"] = expires
                return
        data["transient"].append({
            "statement": statement, "expires_at": expires, "source_id": evidence.source_id,
        })
        return
    # durable：与已有条目撞了原句就当 support，不开重复档
    for pool in ("candidates", "priors"):
        for p in data[pool]:
            if p.get("statement") == statement:
                _support(data, p["id"], evidence)
                return
    now = utcnow_iso()
    data["candidates"].append({
        "id": f"c_{uuid.uuid4().hex[:8]}",
        "statement": statement,
        "kind": "inferred",       # stated（学生明说）将来由宿主 UI 直接写入
        "domain": "learning",
        "evidence": [{"source_id": evidence.source_id, "at": evidence.at,
                      "excerpt": evidence.text[:_EVIDENCE_EXCERPT]}],
        "contradictions": [],
        "status": "candidate",
        "created_at": now, "updated_at": now,
    })
    if len(data["candidates"]) > MAX_CANDIDATES:
        data["candidates"].sort(key=lambda p: p.get("updated_at", ""))
        del data["candidates"][: len(data["candidates"]) - MAX_CANDIDATES]


def distill_evidence(data: dict, evidence: Evidence, llm: Callable[[str], str]) -> dict:
    """把一条证据蒸馏进档案，原地更新并返回。任何一步失败都原样返回（失败关闭）。"""
    try:
        decisions = _parse_decisions(llm(build_prompt(data, evidence)))
    except Exception:
        return data
    for d in decisions:
        try:
            action = d.get("action")
            if action == "support":
                _support(data, d.get("id", ""), evidence)
            elif action == "contradict":
                _contradict(data, d.get("id", ""), evidence)
            elif action == "new":
                _new_observation(data, d.get("statement", ""),
                                 d.get("temporality", "durable"), evidence)
        except Exception:
            continue  # 单条坏 decision 不连坐其他条
    return data
