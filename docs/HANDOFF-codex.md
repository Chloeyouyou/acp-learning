# ACP Learning — 任务交接（给 Codex）

> 交接时间快照。接手前请先读这份，再读 `docs/design/` 与下方"架构铁律"。**别破坏铁律。**

## 0. 一句话
ACP Learning = 面向**零基础学生**的 AI 协同编程学习平台。灵魂闭环：**埋雷 → 学生自己发现 bug → AI 导师「知返」只引导不给答案 → 内化**。卖点不是"AI 讲代码"，是"**AI 陪你学会调试和思考 + 一面认识你的认知镜子**"。

## 1. 怎么跑（Windows / PowerShell + Git Bash 都在用）
- 后端（FastAPI，端口 8000）：在 `backend/` 下
  `PYTHONUTF8=1 .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
  （`PYTHONUTF8=1` 必须，否则中文/特殊字符在 Windows 控制台崩。DB = `backend/acp.db`，SQLite，启动自动建表。）
- 前端（Vite + Vue3）：**必须在 `frontend/` 目录**下 `npx vite build`（本地 vite v6）。
  ⚠️ **坑**：若 cwd 不在 frontend，`npx vite` 会拉到全局 vite v8 且报 "Cannot resolve entry module index.html"。务必 `cd frontend` 再 build。
- 真实测试学号：`stu_n6ooz8`（已有数据，可验证 Timeline/思维默认值/Intervention）。

## 2. 仓库结构 / 关键文件
后端 `backend/app/`：
- `main.py` — 所有 HTTP 端点（/sessions、/run、/submit、/profile、/timeline、/recommendations、/walkthrough…）。
- `services/tutor.py` — **知返**六阶段状态机（①发现→②定位→③归因→④修复→⑤验证→⑥内化）+ 所有 prompt。「LLM 软引导 + 规则硬门控/跃迁」双层。
- `services/mine_engine.py` — 题库加载 + **真跑判题** `judge_fix`（路线A：真执行比对 expected_output，非正则）。
- `services/sandbox.py` — 子进程执行（超时/输出截断/强制 UTF-8）。**本机单用户够用，未隔离**。
- `services/event_engine.py` — 能力事件引擎 `emit` + `log_execution`（写 ExecutionEvent）。
- `services/profile.py` — 画像：能力向量、`knowledge_mastery`（掌握度/证据充足度）、`recommend_practice`（独立可替换）。
- `services/timeline.py` — **B1 派生层（纯读不写库）**：`build_timeline`、`aggregate_thinking_patterns`（思维默认值聚合）、`intervention_for`（开题前小检查）、`THINKING_PATTERNS` taxonomy、`_recurring`。
- `models.py` — 表：TutorSession / Event / ExecutionEvent / CapabilityScore / KnowledgeState。
- `patterns/**/*.yaml` — 15 道题。每题含 `root_cause`(代码机制) / `cognitive_root`(认知漏洞) / `thinking_pattern`(归簇) / `knowledge_points` / `expected_output` / `hint_ladder` / `internalize_questions` 等。

前端 `frontend/src/`：
- `views/Arena.vue` — 训练场（**当前待重设计，见 §5**）。
- `views/Timeline.vue` — 成长轨迹（思维默认值卡 + 时间线 episodes）。
- `views/Profile.vue` — 能力画像（知识点展开卡 + 雷达，标签页）。
- `api.js` / `main.js`(路由) / `App.vue`(顶栏 + logo) / `glossary.js` / `components/`(GlossaryText、RadarChart)。
- `public/favicon.svg`、logo 在 App.vue（暖陶土放射光芒 + 衬线）。

## 3. 架构铁律（违反 = 破坏产品，**禁止**）
1. **用提示不扣分**——这是学习工具不是考试。struggle 信号（失败/RE/WA/HANG/勉强放行）只驱动推荐/强化，**绝不扣能力分**。
2. **Mastery（学会没）与 Confidence（证据是否充足，按 evidence_count）解耦**——只成功一次不算稳定。
3. **知返绝不虚构未发生的事**：学生「提交代码」是动作不是发言；绝不说"你说得对/如你所说"。失败反馈只依据 `[真实运行结果]`。
4. **ExecutionEvent = 事实日志，append-only**：只 INSERT，永不 UPDATE/DELETE；修正用追加 Correction Event。
5. `knowledge_mastery`/`capability_scores` 是**事件流的派生视图**；将来换更聪明的算法**只替换 calculator 函数**，不动事件流 schema。推荐逻辑保持**独立可替换函数**。
6. 知识点别硬编码成扁平字符串（给未来知识图谱留口）。
7. **Reflection vs Intervention**（用户拍板的核心框架）：Timeline=回看的镜子；Arena=做题时的帮手。**干预必须赋能不是评价、不打断**：禁用"你常常/你总是"，不显示 count，文案用"这类题里，先多看一眼：…"。
8. B1 全是**纯派生只读**，不建表、不改事件流。

## 4. 路线图进度（A→B0→B0.5→B1→…）
- ✅ A 沙箱真运行（tag `route-A-sandbox`）
- ✅ B0 数字孪生最小闭环（tag `b0-complete`）：ExecutionEvent + knowledge_mastery + recommend_practice
- ✅ B0.5 观察卡（运行→观察→猜测→导师 软桥，学生消息前缀 `【观察记录】`）
- ✅ B1 Debug Timeline + 认知根因升标题 + 第一次/最近叙事
- ✅ 跨题「思维默认值」聚合（Reflection，tag `b1-thinking-patterns`）
- ✅ Arena 开题前「小检查」Intervention（干预侧，commit `d84b41c`）
- ✅ 训练场 UI v1 + logo（commit `dfdd6a4`，tag `arena-v1`）
- **未来待做**：`thinking_pattern` 自动推断（现作者标注）；"辅助依赖度↓"成长指标；找 3~5 真人内测（方案见 `docs/验证/内测方案.md` + `单人记录表.md`）；之后 D 轻量登录+部署（含沙箱容器化）、E 自动出题。**用户拍板节奏：先内测 → D-lite → E。**

## 5. ⭐ 当前待办任务（接手就做这个）：训练场「认知过程」重设计
**背景**：训练场 UI 反复迭代过很多版（降恐惧、正式终端、知返改名、主线重排、三模块开关）。用户最终提出**最对的方向**——别按"工具"摆（代码/解释/知返），按**认知过程**摆：
```
┌──────────────┬──────────────────────┐
│   代码区      │   思考记录区（主轴）   │
│              │   观察→猜测→验证→总结  │
│              │   + 知返反馈           │
└──────────────┴──────────────────────┘
```
右边永远引导：你观察到什么？你的猜测？如何验证？→ 知返反馈。**「解释代码/逐行讲解」降为"卡住时点开的工具"，不是和主线平级。**

**三条已商定的约束（务必遵守）**：
1. **重组已有，非重写**：六阶段状态机(`tutor.py`)本就按"观察→猜测→验证"提问；观察卡已收"观察+猜测"。这版是把它们**串成一条看得见的思考线**，工作量比看起来小。
2. **温柔，不能变成"填四个框的作业"**（用户花了很多力气降恐惧）：思考记录顺着对话**自然生长**，**永远可跳过、可直接问知返**（保留观察卡的软出口）。不要硬门控"必须先填观察才能问"。
3. **一举多得**：学生填的 观察/猜测/总结 **正好是 Timeline 和「思维默认值」要吃的数据**——界面、教学、数字孪生合成一件事。这是该设计最值钱处。

**工作方式（用户的规矩）**：**先进 plan mode 出完整设计 → 用户评审 → 再写代码**。纯前端优先（尽量不动后端/判题/事件流）。

## 6. 当前 git 状态 / 还原点
- tag `arena-v1`：左右双栏 代码42%/知返58% + logo。**稳定还原点**，回退：`git checkout arena-v1 -- frontend/src/views/Arena.vue`。
- tag `arena-v2-toggle`（**当前 HEAD**）：在 v1 基础上的**「三模块自由开关」**版（代码常驻 + 解释/知返 chip 开关 + flex 自适应 + localStorage 记忆）。
- **两版都已被用户最终方向「认知过程布局」（§5）取代**。接手先决定：**基于 `arena-v2-toggle` 改**（开关/flex 基建可复用）**还是回 `arena-v1` 重做**。
- 计划文件（plan mode 用）：`C:\Users\史雨萱\.claude\plans\cached-dancing-wirth.md`（当前是"三模块"方案，认知过程版尚未写）。

## 7. 用户画像（很重要）
- **零基础**（非程序员），靠真实上手测试驱动，反复亲手抓 bug。
- **审美敏感**：怕"杂/没重点/吓人/土/炒眼睛"；偏好暖陶土+衬线+大留白的克制风（Claude 风）。给方案时**多用"先做一版给看、可一键回退"**而不是抽象问答（多次拒绝 AskUserQuestion，更爱看实物对比）。
- 节奏：常以"试试""继续""好的"推进；要求**先存档/还原点**再大改。
- 已做大量决策（见 §3 铁律 + 记忆文件）。

## 8. 记忆 / 文档
- 项目记忆（跨会话）：`C:\Users\史雨萱\.claude\projects\C--Users----\memory\`（`acp_roadmap_v1.md` 最全、`acp_tutor_state_machine.md`、`project_acp_learning.md`、索引 `MEMORY.md`）。
- 设计文档：`docs/design/06-学生数字孪生MVP.md`、`07-未来演化接口设计.md`。
- 内测：`docs/验证/内测方案.md`、`docs/验证/单人记录表.md`。
