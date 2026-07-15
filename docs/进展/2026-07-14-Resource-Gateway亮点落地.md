# 2026-07-14 · Resource Gateway v2.8.1 亮点落地

## 完成内容

- 评审 `resource-gateway-demo-v2.8.1-5f47c4e`，选择适合当前单体架构的执行信封、用途治理、L0–L5 风险分级、decision/execution 分离与 Evidence 关联。
- 新增轻量动作治理层；未知动作、未知用途、错误发起者默认拒绝。
- 学生运行代码为 L1：
  - 普通闯关 `debug_observation`；
  - ⑤验证 `verify_hypothesis`；
  - Coop `collaborative_debug`。
- 学生提交判题为 L2 `judge_submission`；知返/Agent 不能代提交。
- 每次动作产生唯一 `call_id` 与稳定 `request_digest`，摘要输入包含代码但元数据不保存代码原文。
- 动作上下文写入 `ExecutionEvent.meta`；提交成功产生的能力事件复用同一 `call_id`。
- run / submit 响应和回放代码步骤均暴露 `action_context`。
- 未新增服务、数据库字段或迁移；没有照搬 Demo HMAC、内存 nonce、Mock Token、审批 Token 与 Owner Binding。

## 数据结构

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
  "issued_at": "2026-07-14T...+00:00"
}
```

## 验证

- 新增动作摘要、失败关闭、服务端用途选择、提交证据关联测试。
- 加强 Coop run 与回放测试。
- Python 语法编译通过。
- 全量：108 过 / 0 败 / 6 跳过 / 共 114；跳过均因 Docker 不可用。
