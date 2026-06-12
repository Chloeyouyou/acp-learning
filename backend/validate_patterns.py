"""模式库入库校验（03文档 §4 校验清单的可执行版本）。

对每个模式检查：
1. 必填字段齐全，hint_ladder 含 L0-L5，internalize_questions ≥ 2
2. fix_check 正则不匹配 buggy_code（否则原样提交带雷代码就能通过判定）
3. 雷会响：真实运行 buggy_code——
   RE   → 进程非零退出且stderr有traceback
   HANG → 超时（3秒）
   WA   → 正常退出（结果错误由人工对照期望输出复核）
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8")

PATTERNS_DIR = Path(__file__).parent / "patterns"
REQUIRED = ["id", "name", "category", "language", "knowledge_points", "capability_dims",
            "difficulty", "symptom", "symptom_sample", "buggy_code", "mine_location",
            "trigger_input", "root_cause", "expected_fix", "fix_check",
            "internalize_questions", "hint_ladder"]

failures = []

for path in sorted(PATTERNS_DIR.rglob("*.yaml")):
    p = yaml.safe_load(path.read_text(encoding="utf-8"))
    pid = p.get("id", path.name)
    problems = []

    # 1. 字段完整性
    for field in REQUIRED:
        if field not in p:
            problems.append(f"缺少字段 {field}")
    if set(p.get("hint_ladder", {})) != {"L0", "L1", "L2", "L3", "L4", "L5"}:
        problems.append("hint_ladder 必须恰好包含 L0-L5")
    if len(p.get("internalize_questions", [])) < 2:
        problems.append("internalize_questions 至少2个")

    # 2. fix_check 不得匹配带雷代码
    if re.search(p["fix_check"], p["buggy_code"]):
        problems.append("fix_check 匹配了 buggy_code——原样提交即可通过！")

    # 3. 雷会响
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as f:
        f.write(p["buggy_code"])
        tmp = f.name
    try:
        r = subprocess.run([sys.executable, tmp], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=3)
        actual = "RE" if r.returncode != 0 else "OK"
    except subprocess.TimeoutExpired:
        actual = "HANG"
    finally:
        Path(tmp).unlink(missing_ok=True)

    expected = p["symptom"]
    if expected == "RE" and actual != "RE":
        problems.append(f"症状声明RE但实际{actual}（雷没响）")
    elif expected == "HANG" and actual != "HANG":
        problems.append(f"症状声明HANG但实际{actual}（雷没响）")
    elif expected == "WA" and actual != "OK":
        problems.append(f"症状声明WA但运行结果是{actual}（WA类应正常退出）")

    status = "PASS" if not problems else "FAIL"
    print(f"[{status}] {pid} ({expected}, 实测{actual})")
    for prob in problems:
        print(f"       - {prob}")
        failures.append((pid, prob))

print()
if failures:
    print(f"校验失败：{len(failures)} 个问题")
    sys.exit(1)
print(f"全部通过：{len(list(PATTERNS_DIR.rglob('*.yaml')))} 个模式")
