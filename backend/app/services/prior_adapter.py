"""认知先验层的 ACP 适配器——ACP 认识 priors，priors 不认识 ACP（拆卸纪律）。

写入：内化结算沉淀经历后，把经历摘要作为证据喂给蒸馏（摘要本就不含
expected_fix，天然继承经历层的泄题硬门控）。读取：开局/每轮构建 system
prompt 时注入 active 先验，无先验时返回空串、行为与现状完全一致。

保险丝：env ACP_PRIORS=off 时读写全无操作；蒸馏/注入任何异常都静默吞掉，
绝不影响结算与对话主流程（失败关闭）。存储在 priors_data/（ACP_PRIORS_DIR
可覆盖），不进数据库——迁移=搬目录，学生本人可直接打开纠正。
"""

import os
from pathlib import Path

from openai import OpenAI

from ..config import BASE_DIR, DEEPSEEK_BASE_URL, TUTOR_MODEL
from ..priors import Evidence, PriorStore, distill_evidence, render_injection, utcnow_iso

_client = None


def _enabled() -> bool:
    return os.environ.get("ACP_PRIORS", "on").lower() not in ("off", "0", "false")


def _store() -> PriorStore:
    # 目录每次现读 env——测试与运维改开关/挪目录不用重启进程
    return PriorStore(Path(os.environ.get("ACP_PRIORS_DIR") or BASE_DIR / "priors_data"))


def _llm(prompt: str) -> str:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"),
                         base_url=DEEPSEEK_BASE_URL, timeout=30.0)
    resp = _client.chat.completions.create(
        model=TUTOR_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    return resp.choices[0].message.content or ""


def feed_from_experience(exp) -> None:
    """结算钩子：一条新经历 → 一次蒸馏。exp 是 StudentExperience（只读 summary 等字段）。"""
    if not _enabled():
        return
    try:
        store = _store()
        data = store.load(exp.student_id)
        evidence = Evidence(text=exp.summary, source_id=exp.session_id, at=utcnow_iso())
        store.save(exp.student_id, distill_evidence(data, evidence, _llm))
    except Exception:
        pass  # 失败关闭：蒸馏挂了不许波及结算主流程


def injection_for(student_id: str) -> str:
    """注入钩子：拼进导师 system prompt 的文本块；无先验/关闭/出错都返回空串。"""
    if not _enabled():
        return ""
    try:
        return render_injection(_store().load(student_id))
    except Exception:
        return ""
