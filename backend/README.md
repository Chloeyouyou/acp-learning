# ACP Learning — 后端 MVP

按 `docs/design/01-05` 各文档的 MVP 范围实现的最小闭环：

```text
埋雷引擎（模板题）→ AI导师（六阶段状态机 + 引导阶梯）→ 能力事件（rule + llm_judge）→ 画像（向量 + 状态机）
```

## 启动

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # 填入 DEEPSEEK_API_KEY
uvicorn app.main:app --reload
```

接口文档：http://127.0.0.1:8000/docs

## 核心流程（API 调用顺序）

```text
POST /api/sessions                       # 埋雷：返回带雷代码（学生不可见雷信息）
POST /api/sessions/{id}/messages         # 共脑对话：导师引导，产出LLM判定事件
POST /api/sessions/{id}/submit           # 提交修复：规则判定（fix_check正则），产出规则事件
GET  /api/students/{id}/profile          # 画像：能力向量 + 维度 + 知识点状态
GET  /api/students/{id}/capabilities/{cap}/events   # 下钻：每个分数背后的事件与evidence
```

## 模块对应关系

| 代码 | 设计文档 |
|------|----------|
| `app/services/mine_engine.py` | 01 埋雷引擎（MVP：模板题 + MineManifest） |
| `app/services/tutor.py` | 02 AI导师（状态机①-⑤、引导阶梯、行为红线、结构化事件输出；LLM后端为DeepSeek） |
| `patterns/*/*.yaml` | 03 Bug模式库（首批3个种子模式，目标15个） |
| `app/services/event_engine.py` + `app/registry.py` | 04 能力事件（注册表校验、双生产者、置信度过滤） |
| `app/services/profile.py` | 05 画像（向量更新算法、知识点状态机、下钻） |

## MVP 已实现 / 未实现

已实现：
- 雷状态机 planted→found→fixed，跃迁触发规则事件
- 导师结构化输出（`messages.parse` + Pydantic），LLM事件白名单4类 + 置信度<0.7不入画像
- 画像冷启动（前10事件K翻倍）、events_count置信度标记、知识点「已接触/已解决」

未实现（V0.3）：
- 内化三关（反向提问/复述/变式）与「已内化」跃迁
- 沙箱真实运行判题（当前用 fix_check 正则）
- 剩余12个Bug模式、变换注入、选雷策略个性化
- 时间衰减、防刷分重复衰减、Vibe Coding双角色
