"""【dev-only】给指定学生造一道「已解决 + N 天前」的可复习数据，用于人工验收复习队列。

绝不进学生端、不进部署运行时——纯本地调试工具（脚本风格仿 validate_patterns.py）。

用法：
  python seed_review.py <student_id> [--pattern BP-BOUNDARY-001] [--days 10] [--state 已解决]
  python seed_review.py stu_n6ooz8            # 默认：边界题、10天前、已解决
之后打开「成长轨迹」页，顶部应出现「🔁 今日复习」卡片。
"""

import argparse
import sys
import uuid
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")

from app.db import SessionLocal, init_db
from app.models import ExecutionEvent, KnowledgeState, TutorSession
from app.services import mine_engine


def main():
    ap = argparse.ArgumentParser(description="造可复习数据（dev-only）")
    ap.add_argument("student_id")
    ap.add_argument("--pattern", default="BP-BOUNDARY-001")
    ap.add_argument("--days", type=int, default=10, help="多少天前解决（决定是否到期）")
    ap.add_argument("--state", default="已解决", choices=["已解决", "已内化"])
    args = ap.parse_args()

    init_db()
    mine_engine.load_patterns()
    try:
        pat = mine_engine.get_pattern(args.pattern)
    except KeyError:
        print(f"✗ 题库里没有 {args.pattern}")
        sys.exit(1)

    db = SessionLocal()
    solved_at = (datetime.now() - timedelta(days=args.days)).isoformat()
    sess_id = f"sess_seed_{uuid.uuid4().hex[:8]}"

    # 一条解决会话（让 timeline 也能串得起来）
    db.add(TutorSession(
        id=sess_id, student_id=args.student_id, pattern_id=args.pattern,
        manifest={"mode": "debug", "mines": [{"internalize_questions": []}]},
        stage="⑤验证", mine_status="fixed" if args.state == "已解决" else "internalized",
        status="completed", history=[], created_at=solved_at))
    # 一条 submit/OK 执行事实（review.due_queue 据此算 last_solved_at/轮次）
    db.add(ExecutionEvent(
        id=f"ex_{uuid.uuid4().hex[:12]}", version="v1", student_id=args.student_id,
        session_id=sess_id, pattern_id=args.pattern, source="submit", kind="OK",
        knowledge_points=pat.get("knowledge_points", []),
        meta={"mode": "debug"}, timestamp=solved_at))
    # 知识状态：复习资格来源
    existing = db.get(KnowledgeState, {"student_id": args.student_id, "pattern_id": args.pattern})
    if existing:
        existing.state = args.state
        existing.updated_at = solved_at
    else:
        db.add(KnowledgeState(
            student_id=args.student_id, pattern_id=args.pattern,
            knowledge_points=pat.get("knowledge_points", []),
            state=args.state, updated_at=solved_at))
    db.commit()
    db.close()

    print(f"✓ 已为 {args.student_id} 造好可复习数据：")
    print(f"  题：{pat['name']}（{args.pattern}）")
    print(f"  状态：{args.state}，{args.days} 天前解决")
    print(f"  打开『成长轨迹』页，顶部应出现「今日复习」卡片。")


if __name__ == "__main__":
    main()
