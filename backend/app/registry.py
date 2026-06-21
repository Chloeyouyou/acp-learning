"""能力类型注册表（04文档 §4）。封闭集合：事件入库时校验，未注册类型一律拒绝。"""

CAPABILITY_REGISTRY = {
    "Log_Reading":          {"zh": "日志阅读",   "dimension": "Debug能力",   "weight": 0.15},
    "Boundary_Awareness":   {"zh": "边界意识",   "dimension": "Debug能力",   "weight": 0.20},
    "Root_Cause_Reasoning": {"zh": "根因分析",   "dimension": "Debug能力",   "weight": 0.30},
    "Independent_Debug":    {"zh": "独立调试",   "dimension": "Debug能力",   "weight": 0.25},
    "Hypothesis_Testing":   {"zh": "假设验证",   "dimension": "Debug能力",   "weight": 0.10},
    "Internalization":      {"zh": "内化",       "dimension": "*",          "weight": 0.0},
    "AI_Review":            {"zh": "AI代码审查", "dimension": "AI协作能力",  "weight": 0.35},
    "AI_Verification":      {"zh": "AI回答验证", "dimension": "AI协作能力",  "weight": 0.35},
    "Prompt_Design":        {"zh": "提示词设计", "dimension": "AI协作能力",  "weight": 0.30},
}

# LLM 允许产出的能力事件类型。Prompt_Design 随提问训练 P1-full 启用（04文档 §4.10 主 producer=llm_judge）。
LLM_ALLOWED_CAPABILITIES = {
    "Root_Cause_Reasoning",
    "Hypothesis_Testing",
    "Independent_Debug",
    "AI_Verification",
    "Prompt_Design",
}

DELTA_MIN, DELTA_MAX = -3, 3
