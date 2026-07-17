"""受控工具动作的最小治理层。

借鉴 Resource Gateway 的执行信封、用途白名单、风险分级和 decision/execution 分离，
但保持 ACPLearning 单体架构：这里不做代理、不接管身份认证，只在端点完成既有身份校验后
为真实工具动作生成可信元数据，并对未知动作/用途和 Agent 代提交失败关闭。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal


ExecutionState = Literal["pending", "completed", "failed", "simulated"]


class ActionDenied(ValueError):
    """动作不在服务端策略白名单内；调用方不得自行指定风险级别绕过。"""


@dataclass(frozen=True)
class ActionPolicy:
    risk_level: int
    allowed_purposes: frozenset[str]
    allowed_initiators: frozenset[str]


ACTION_POLICIES = {
    "sandbox.run": ActionPolicy(
        risk_level=1,
        allowed_purposes=frozenset({
            "debug_observation", "verify_hypothesis", "collaborative_debug",
        }),
        allowed_initiators=frozenset({"student"}),
    ),
    "submission.judge": ActionPolicy(
        risk_level=2,
        allowed_purposes=frozenset({"judge_submission"}),
        # 硬门：知返可以建议提交，但不能替学生触发会改变学习状态的判题动作。
        allowed_initiators=frozenset({"student"}),
    ),
}


def purpose_for_run(*, stage: str, mode: str) -> str:
    """用途由服务端状态决定，不接受客户端自报。"""
    if mode == "coop":
        return "collaborative_debug"
    if stage == "⑤验证":
        return "verify_hypothesis"
    return "debug_observation"


def _request_digest(*, action: str, purpose: str, payload: dict) -> str:
    canonical = json.dumps(
        {"action": action, "purpose": purpose, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"req_{hashlib.sha256(canonical).hexdigest()[:24]}"


def authorize_action(*, actor_id: str, session_id: str, action: str, purpose: str,
                     initiated_by: str, payload: dict) -> dict:
    """校验服务端动作策略并生成可落入事件 meta 的执行上下文。

    payload 只参与摘要，不会原样进入返回值，避免把学生代码复制进元数据。
    """
    policy = ACTION_POLICIES.get(action)
    if policy is None:
        raise ActionDenied(f"action_denied: 未注册动作 '{action}'")
    if purpose not in policy.allowed_purposes:
        raise ActionDenied(f"purpose_denied: 动作 '{action}' 不允许用途 '{purpose}'")
    if initiated_by not in policy.allowed_initiators:
        raise ActionDenied(
            f"initiator_denied: '{initiated_by}' 不能触发动作 '{action}'"
        )

    return {
        "call_id": f"call_{uuid.uuid4().hex[:24]}",
        "request_digest": _request_digest(
            action=action, purpose=purpose, payload=payload,
        ),
        "actor_id": actor_id,
        "session_id": session_id,
        "agent_id": "zhifan",
        "action": action,
        "purpose": purpose,
        "risk_level": policy.risk_level,
        "initiated_by": initiated_by,
        "decision": "allow",
        "execution": "pending",
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }


def with_execution(context: dict, execution: ExecutionState) -> dict:
    """返回更新后的副本，保留授权决策与实际执行结果为两个独立维度。"""
    updated = dict(context)
    updated["execution"] = execution
    return updated
