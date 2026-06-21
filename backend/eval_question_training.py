"""提问训练判定稳定性评测（P1 前置：量一量 LLM 三要素判定准不准、稳不稳）。

⚠️ 会真连 LLM、要花钱/时间，所以独立于 run_tests.py，手动跑：
    .venv/Scripts/python.exe eval_question_training.py [每条重复次数，默认3]

衡量两件事：
  · 一致性（稳）：同一条提问跑 N 遍，三要素布尔是否每次都一样（抖动=P1 会污染画像）。
  · 准确性（准）：与人工标注的期望三要素是否吻合。
P1 加分前应先看这两个达标。
"""

import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

from app.services import question_training as q

# 固定测试集：(场景, 提问, 期望[现,上,预])。覆盖 差/中/好。
# 期望按灵犀宽松尺度人工标注；borderline 用 None 表示"不强校准、只看一致性"。
CASES = [
    # —— 差：三要素基本全无 ——
    ("login", "代码报错了", (False, False, False)),
    ("login", "帮我看看", (False, False, False)),
    ("login", "不知道为什么不行", (False, False, False)),
    ("wrong_result", "这个函数有问题", (False, False, False)),
    # —— 中：1~2 个要素 ——
    ("login", "登录功能一直登不上去", (True, True, False)),      # 现(登不上去)+上(登录功能)
    ("login", "报错了，提示 NullPointerException", (True, False, False)),  # 现
    ("login", "我希望点登录后能成功进入系统", (False, False, True)),  # 预
    ("list_empty", "列表页打开是空白的", (True, True, False)),    # 现(空白)+上(列表页)
    ("wrong_result", "计算结果和我预期的对不上", (True, False, True)),  # 现+预
    ("login", "登录的时候报了个错", (True, True, False)),         # 现+上(登录)
    # —— 好：三要素齐 ——
    ("login", "我点登录按钮后页面没反应，希望能正常登录进去", (True, True, True)),
    ("login", "登录报 NullPointerException，在 UserService 第32行，期望完成登录返回用户信息", (True, True, True)),
    ("list_empty", "列表页打开后一直空白，数据出不来，我期望它显示用户列表", (True, True, True)),
    ("wrong_result", "我的求和函数 sum_list 返回 0，输入 [1,2,3] 期望得到 6", (True, True, True)),
]

REPEAT = int(sys.argv[1]) if len(sys.argv) > 1 else 3


def _flags(r):
    return (r["phenomenon"], r["context"], r["expectation"])


def main():
    print(f"提问训练判定稳定性评测 · 每条跑 {REPEAT} 遍 · 共 {len(CASES)} 条\n")
    print(f"{'提问':<34} {'期望':>9}  {'各遍结果(现上预)':<22} {'一致':<5} {'命中期望'}")
    print("-" * 92)

    consistent_n = 0
    accurate_runs = total_runs = 0
    flaky = []

    for scenario, prompt, expected in CASES:
        runs = [_flags(q.diagnose(scenario, prompt)) for _ in range(REPEAT)]
        # 一致性：N 遍是否完全相同
        most = Counter(runs).most_common(1)[0]
        is_consistent = most[1] == REPEAT
        consistent_n += is_consistent
        if not is_consistent:
            flaky.append((prompt, runs))
        # 准确性：每遍与期望比（期望含 None 的位跳过）
        for run in runs:
            total_runs += 1
            ok = all(e is None or e == a for e, a in zip(expected, run))
            accurate_runs += ok

        exp_s = "".join("T" if e else ("?" if e is None else "F") for e in expected)
        runs_s = " ".join("".join("T" if x else "F" for x in r) for r in runs)
        mode_run = most[0]
        hit = all(e is None or e == a for e, a in zip(expected, mode_run))
        p = (prompt[:31] + "…") if len(prompt) > 32 else prompt
        print(f"{p:<34} {exp_s:>9}  {runs_s:<22} {'稳' if is_consistent else '抖':<5} {'✓' if hit else '✗'}")

    print("-" * 92)
    print(f"\n一致性（稳）：{consistent_n}/{len(CASES)} 条 N 遍完全一致"
          f"（{consistent_n / len(CASES):.0%}）")
    print(f"准确性（准）：{accurate_runs}/{total_runs} 遍命中期望（{accurate_runs / total_runs:.0%}）")
    if flaky:
        print(f"\n抖动条（同句不同判，P1 加分前重点关注）：")
        for prompt, runs in flaky:
            runs_s = " | ".join("".join("T" if x else "F" for x in r) for r in runs)
            print(f"  · 「{prompt}」 → {runs_s}")
    print("\n建议门槛（P1 emit 前）：一致性 ≥90%、准确性 ≥85%；抖动条优先靠 few-shot/措辞收敛。")


if __name__ == "__main__":
    main()
