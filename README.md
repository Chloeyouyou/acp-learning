# ACP Learning — AI协同编程学习系统

一个以 **AI协同学习** 为核心的编程教育平台。不做传统 OJ 判题，而是通过「埋雷 → AI共脑解决 → 理解内化」的教学闭环，让学生在与 AI 协作中学会编程、学会调试、学会提问、学会正确地 Vibe Coding。

> 一句话定位：GitHub Copilot + Claude + 编程教育 + 能力画像 + AI共脑训练

## 核心模块

| 模块 | 说明 |
|------|------|
| AI共脑调试空间 | AI不给答案，通过提示→追问→引导→验证训练Debug能力 |
| Bug闯关训练场 | 埋雷引擎植入真实Bug，完整走「发现→共脑→修复→内化」闭环 |
| Vibe Coding训练场 | 引导式需求分析与系统设计，训练AI代码审查能力 |
| AI提问能力训练 | 评估Prompt质量，培养向AI提问的能力 |
| 能力画像系统 | 记录"掌握了什么能力"，区分「已解决」与「已内化」 |

## 项目结构

```text
acp-learning/
├── docs/
│   ├── 产品概念方案-V0.1.md
│   └── design/                  # V0.2 核心资产设计（埋雷→导师→事件→画像闭环）
│       ├── 01-埋雷引擎设计.md
│       ├── 02-AI导师策略设计.md
│       ├── 03-Bug模式库设计.md
│       ├── 04-能力事件模型.md
│       └── 05-学生能力画像模型.md
├── backend/     # FastAPI：埋雷引擎/AI导师(DeepSeek)/事件引擎/画像 + 15模式题库
├── frontend/    # Vue3 + Vite：训练场（代码+导师对话）/ 画像页（雷达图+事件下钻）
└── README.md
```

## 快速启动

```powershell
# 后端（先复制 backend/.env.example 为 .env 填入 DEEPSEEK_API_KEY）
cd backend; .venv\Scripts\activate; uvicorn app.main:app --port 8000

# 前端（另开一个终端）
cd frontend; npm install; npm run dev   # 打开 http://localhost:5173
```

## 路线图

- [x] V0.1 产品概念方案
- [x] V0.2 核心设计：埋雷引擎、AI导师策略、Bug模式库（首批15模式）、能力事件模型（9类事件）、能力画像模型
- [x] MVP 后端：埋雷→导师→事件→画像闭环（含15模式题库与入库校验）
- [x] MVP 前端：Bug闯关训练场 + 能力画像页
- [ ] V0.3：内化三关（反向提问/复述/变式）与「已内化」跃迁、沙箱真实判题、间隔复现队列
- [ ] Vibe Coding训练场与提问能力训练
- [ ] 本体扩展：知识点本体 → 错误模式本体 → 能力本体 → 学生数字孪生
