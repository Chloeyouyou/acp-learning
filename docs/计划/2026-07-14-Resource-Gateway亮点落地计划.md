# Resource Gateway v2.8.1 亮点落地计划（2026-07-14）

## 1. 背景与目标

参考 `resource-gateway-demo-v2.8.1-5f47c4e` 的执行信封、用途治理、L0–L5 风险分级、授权/执行分离与 Evidence 关联设计，为 ACPLearning 的真实工具动作补上可执行治理和跨事件追踪。

本轮只实施适合当前单体 FastAPI 的最小版本：**不引入独立 Gateway 服务、不修改事件流四张表 schema、不照搬 Demo HMAC/内存 nonce/Mock Token。**

## 2. 本轮范围

### 2.1 结构化动作上下文

为受治理动作生成：

- `call_id`：每次动作唯一；
- `request_digest`：请求内容摘要，不保存代码原文；
- `actor_id` / `session_id` / `agent_id`；
- `action` / `purpose` / `risk_level`；
- `initiated_by`；
- `decision` 与 `execution`；
- `issued_at`。

### 2.2 确定性用途与风险策略

| 动作 | 用途 | 风险 | 门控 |
|---|---|---:|---|
| `sandbox.run` | `debug_observation` / `verify_hypothesis` / `collaborative_debug` | L1 | 登录学生主动触发 |
| `submission.judge` | `judge_submission` | L2 | 只能由学生主动触发，Agent 不得代提交 |

未知动作、未知用途默认拒绝；风险级别不由客户端传入。

### 2.3 接入点

- 闯关 `/run`；
- 闯关 `/submit`；
- Coop `/run`（复用 `tutor.run_and_inject`）；
- `ExecutionEvent.meta.action_context`；
- 修复成功能力事件 `Event.context.action_context`；
- API 响应中的 `action_context`，便于前端和联调观测。

## 3. 明确不做

- 不加入独立 Resource Gateway 进程；
- 不新增数据库字段或迁移；
- 不引入审批 Token、Owner Binding、Skill Manifest；
- 不把普通聊天当高风险工具动作；
- 不把 `purpose` 当成防泄题的唯一安全机制；导师泄题仍由现有状态机和红线约束。

## 4. 实施步骤与验收

1. [x] 新增纯函数动作治理模块和失败关闭规则。
2. [x] 扩展执行事实写入，合并动作上下文但保持原 `meta` 字段兼容。
3. [x] 接入 run / submit / coop-run，区分授权结果和执行结果。
4. [x] 修复成功能力事件关联同一 `call_id`。
5. [x] 新增测试：摘要稳定且不含原代码、未知动作拒绝、Agent 代提交拒绝、run/submit 元数据与事件关联。
6. [x] 全量测试通过并记录结果。

验收示例：

```json
{
  "call_id": "call_...",
  "request_digest": "req_...",
  "actor_id": "student-001",
  "session_id": "sess_...",
  "agent_id": "zhifan",
  "action": "submission.judge",
  "purpose": "judge_submission",
  "risk_level": 2,
  "initiated_by": "student",
  "decision": "allow",
  "execution": "completed",
  "issued_at": "..."
}
```

## 5. 实施结果

- 新增 `backend/app/services/action_governance.py`，风险和用途完全由服务端白名单决定。
- `sandbox.run` 接入闯关与 Coop；阶段⑤自动使用 `verify_hypothesis`，Coop 使用 `collaborative_debug`。
- `submission.judge` 固定 L2 且仅允许 `initiated_by=student`；未知动作与 Agent 代提交失败关闭。
- `ExecutionEvent.meta.action_context` 保存执行上下文；不保存代码原文，只保存稳定摘要。
- 修复成功的 `Independent_Debug` 能力事件在 `Event.context.action_context` 中复用同一 `call_id`。
- 回放的代码步骤直接返回 `action_context`，前端可按 `call_id` 关联动作、快照和能力事件。
- run / submit API 响应返回 `action_context`。
- 全量验证：**108 过 / 0 败 / 6 跳过 / 共 114**；6 项均为本机无 Docker 时按既有规则跳过的隔离测试。
