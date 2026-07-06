# CLAUDE.md — ACP Learning 协作规范

> 这份文件每次会话自动加载。**新会话开始先读它**，就能接上上次的进度和工作方式。

## 项目一句话

AI 协同编程学习系统——不做判题，做**过程化陪练**。核心闭环：**埋雷 → AI 共脑调试 → 内化**。
产品定位见 `README.md` 与 `docs/产品概念方案-V0.1.md`；架构现状见最新体检 `docs/审计/`。

---

## 新会话怎么接上（按顺序做这三步）

1. **读最新工作日志**：`docs/进展/` 里日期最新的一篇 —— 上次做到哪、下一步是什么、有哪些设计决策。
2. **看当前计划**：`docs/计划/` 里最新的一份 —— 里程碑的勾选状态与验收标准。
3. **跑测试确认基线绿**：`cd backend && .venv/Scripts/python.exe run_tests.py`（应全过）。

---

## 工作流程（每次都照这个走）

1. **先计划，后动手**（重要）：接到一个任务/里程碑，**先写或更新计划文档**（`docs/计划/`）——列清要做什么、分几步、每步验收标准，**保存**。然后才开始写代码。不要边想边写。
2. **较大里程碑开特性分支**：`git checkout -b mX-xxx`。`main` 始终保持稳定、可部署。
3. **每完成一个可验证单元就 commit**：一块功能 + 对应测试跑绿 → 提交，消息写清「做了什么、为什么」。不攒一大坨再提交。
4. **里程碑做完**：`git merge --no-ff` 合回 main → `git push`（会触发 Render 自动部署）。
   - 注意：`git merge -F -` 不支持 stdin，用临时文件 `-F <file>` 或 `-m`。
5. **会话收尾**：更新工作日志（`docs/进展/日期.md`，记全当天改动 + 设计决策）+ 勾选计划 + 需要时更新记忆。

---

## 铁律（改动前必须守住）

- **事件流四张表 schema 不动**：`events` / `execution_events` / `capability_scores` / `knowledge_states`。能力评估都是可重放的**派生视图**，换更聪明的模型只改派生函数，不迁 schema。
- **append-only 的表只 INSERT，永不 UPDATE/DELETE**：`execution_events` / `code_snapshots` / `session_messages`。
- **导师红线**：绝不泄题（任何提示级别都不给能直接抄的代码/确切改法）、绝不臆断没真实运行过的结果。见 `tutor.py` 的 SYSTEM_TEMPLATE。
- **改 model 必须配 alembic 迁移**：`alembic revision --autogenerate -m "..."`，然后**人工检查生成的迁移**（SQLite 不支持某些 ALTER，autogenerate 可能生成坏 DDL），再 `alembic upgrade head`；跑 `alembic check` 确认无残留 drift。

---

## 常用命令

- 跑测试：`cd backend && .venv/Scripts/python.exe run_tests.py`
- 本地起全栈：双击根目录 `start.bat`（后端 uvicorn + 前端 vite），打开 http://localhost:5173
- 迁移：`cd backend && .venv/Scripts/alembic.exe upgrade head`
- 沙箱后端切换：环境变量 `ACP_SANDBOX=docker|subprocess|auto`（无 docker 自动降级 subprocess）
- 线上健康检查：`curl https://acp-learning.onrender.com/api/health`（看 version + sandbox 后端）

---

## 关键架构备忘

- 后端 FastAPI（`backend/app/`）：`main.py` 路由、`services/` 业务（`tutor.py` 六阶段状态机是皇冠资产，改动谨慎）、`security.py` token、`concurrency.py` 会话锁、`process.py` 代码快照+消息时间线+回放。
- 身份：无密码 HMAC token，`current_student` 依赖取身份，`require_self` 越权门。所有 `/students/{id}/*` 只认 token 不认自报 id。
- 前端 Vue3 + vue-router（`frontend/src/views/`）。api.js 统一带 Authorization。
- 部署：单 Docker 服务同源托管前端 dist；Render 从 main 自动部署（无 docker → 沙箱走 subprocess）。真上全校需 VPS + docker 隔离 + Postgres。

---

## 下一步（动手前先按流程第 1 条写计划）

- **M3b 课程/单元 + 地图页**：把 23 道平铺题组织成「单元→关卡」，大厅瘦身三卡。
- 之后 **M4 教师端**：班级总览（每人进度/卡点）。
- 详见 `docs/计划/2026-07-05-v2过程化升级计划.md`。
