"""【dev-only / 绝不进部署运行时】造「接着做」验收数据。

给一个测试学生造 3 个不同阶段、不同活跃时间的未完成（active）会话，
每个都带真实学生发言 + 执行事件——确保不被空壳清理、且「继续上次」能真恢复。

用法（后端 venv）：
    python seed_active.py            # 默认学生 stu_demo
    python seed_active.py stu_xxx    # 指定学生
"""

import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")

from app.db import SessionLocal, init_db
from app.models import ExecutionEvent, TutorSession
from app.services import mine_engine


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


# (题, 阶段, mine_status, 活跃于多久前, 一段真实对话)
PLAN = [
    ("BP-BOUNDARY-001", "①发现", "planted", timedelta(days=2), [
        {"role": "user", "content": "我运行了一下，好像报了 IndexError，但不确定为什么。"},
        {"role": "assistant", "content": "很好，你已经注意到报错了。先看看是哪一行触发的？"},
    ]),
    ("BP-LOOP-001", "③归因", "found", timedelta(hours=5), [
        {"role": "user", "content": "我觉得是循环的终止条件写错了，停在了第 4 行。"},
        {"role": "assistant", "content": "你已经定位到雷了。那你觉得这个条件为什么会让循环停不下来？"},
        {"role": "user", "content": "因为 i 一直没有变大？"},
    ]),
    ("BP-NULL-001", "⑤验证", "fixed", timedelta(minutes=10), [
        {"role": "user", "content": "我加了判空，现在不报错了。"},
        {"role": "assistant", "content": "修好了！那我们验证一下——你能想一个边界输入来检验它吗？"},
    ]),
]


def main():
    student_id = sys.argv[1] if len(sys.argv) > 1 else "stu_demo"
    init_db()
    db = SessionLocal()
    created = []
    for pid, stage, mine_status, ago, history in PLAN:
        pattern = mine_engine.get_pattern(pid)
        manifest = mine_engine.build_manifest(student_id, pattern)
        manifest["mode"] = "debug"
        active_at = _now() - ago
        ssid = f"sess_{uuid.uuid4().hex[:12]}"
        db.add(TutorSession(
            id=ssid, student_id=student_id, pattern_id=pid, manifest=manifest,
            stage=stage, mine_status=mine_status, history=history, status="active",
            created_at=_iso(active_at)))
        # 一条执行事件，时间戳 = 活跃时间，驱动 active-sessions 的倒序排序
        db.add(ExecutionEvent(
            id=f"ex_{uuid.uuid4().hex[:12]}", version="v1", student_id=student_id,
            session_id=ssid, pattern_id=pid, source="run", kind="OK",
            knowledge_points=pattern.get("knowledge_points", []), meta={},
            timestamp=_iso(active_at)))
        created.append((pattern.get("name", pid), stage, ago))
    db.commit()
    db.close()

    print(f"\n✓ 已为学生 {student_id} 造 {len(created)} 个未完成会话：")
    for name, stage, ago in sorted(created, key=lambda x: x[2]):
        print(f"   - {name}  停在 {stage}  活跃于 {ago} 前")
    print(f"\n在浏览器控制台执行下面一行，把当前账号切到这个测试学生：")
    print(f"   localStorage.setItem('student_id','{student_id}'); location.reload()")


if __name__ == "__main__":
    main()
