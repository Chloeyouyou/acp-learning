"""题库入库校验（复用 app.services.pattern_validator，单一来源）。

对 patterns/ 下每个已入库题（不含 _pending 候选）跑：结构完整 + fix_check 不匹配带雷码 + 雷会响。
用法：在 backend/ 下 `python validate_patterns.py`
"""

import sys
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8")

from app.services import pattern_validator  # noqa: E402

PATTERNS_DIR = Path(__file__).parent / "patterns"

failures = []
checked = 0
for path in sorted(PATTERNS_DIR.rglob("*.yaml")):
    if "_pending" in path.parts:   # 候选题未入库，不校验
        continue
    checked += 1
    p = yaml.safe_load(path.read_text(encoding="utf-8"))
    pid = p.get("id", path.name)
    problems = pattern_validator.validate_library_pattern(p)
    print(f"[{'PASS' if not problems else 'FAIL'}] {pid}")
    for prob in problems:
        print(f"       - {prob}")
        failures.append((pid, prob))

print()
if failures:
    print(f"校验失败：{len(failures)} 个问题")
    sys.exit(1)
print(f"全部通过：{checked} 个模式")
