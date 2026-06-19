"""作者侧 CLI：自动出题。生成→沙箱双关质检→重试→落 patterns/_pending/。

例：
  python -m app.tools.gen_patterns --category null --difficulty L2 \
        --thinking assume_valid --symptom RE -n 3
过闸的题落 _pending，需再用 review_patterns 人审后入库。
"""

import argparse

from ..services import generation_planner, pattern_factory


def main():
    ap = argparse.ArgumentParser(description="自动出题（落 _pending，待人审入库）")
    ap.add_argument("--category", required=True, choices=["boundary", "loop", "null", "arithmetic"])
    ap.add_argument("--difficulty", required=True, choices=["L1", "L2", "L3", "L4", "L5"])
    ap.add_argument("--thinking", required=True, choices=[
        "assume_valid", "index_confusion", "loop_progress",
        "crash_site", "control_semantics", "shared_state"])
    ap.add_argument("--symptom", required=True, choices=["RE", "WA", "HANG"])
    ap.add_argument("--kp", nargs="*", default=None, help="倾向的知识点（中文）")
    ap.add_argument("--seed", default=None, help="场景种子，如 '成绩单/购物车'")
    ap.add_argument("-n", type=int, default=1)
    ap.add_argument("--retries", type=int, default=3)
    args = ap.parse_args()

    tasks = generation_planner.plan_tasks(
        category=args.category, difficulty=args.difficulty, thinking_pattern=args.thinking,
        error_target=args.symptom, knowledge_points=args.kp, n=args.n, seed=args.seed)
    res = pattern_factory.generate_batch(tasks, retries=args.retries)

    print(f"\n=== 完成：过闸 {len(res['accepted'])} 道、失败 {len(res['failed'])} 个任务 ===")
    if res["accepted"]:
        print("过闸（落 _pending，待 review）：", ", ".join(res["accepted"]))
        print("下一步：python -m app.tools.review_patterns --list")


if __name__ == "__main__":
    main()
