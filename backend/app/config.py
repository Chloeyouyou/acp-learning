from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
PATTERNS_DIR = BASE_DIR / "patterns"
DATABASE_URL = f"sqlite:///{BASE_DIR / 'acp.db'}"

TUTOR_MODEL = "claude-opus-4-8"

# 04-能力事件模型 §2.2：低于此置信度的LLM判定事件入库但不参与画像
CONFIDENCE_THRESHOLD = 0.7

# 05-学生能力画像模型 §3：分值更新参数（集中一处便于调参）
BASE_STEP = 3
COLD_START_EVENTS = 10
COLD_START_FACTOR = 2.0
INITIAL_SCORE = 30

# 02-AI导师策略 §1：阶段流转顺序
STAGES = ["①发现", "②定位", "③归因", "④修复", "⑤验证", "⑥内化"]
HINT_LEVELS = ["L0", "L1", "L2", "L3", "L4", "L5"]
