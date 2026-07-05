"""会话回合锁（M1 D4-5）。串行化同一会话的一次「回合」，堵两类并发事故：

- **丢写（R2）**：两个并发请求同时读 `session.history`、各自 append、各自整块写回 →
  后写覆盖先写，丢一条消息。锁让第二个请求等第一个提交完再进。
- **提交 TOCTOU（审计 #12）**：两个并发 submit 都通过「mine_status != fixed」判定 →
  重复结算能力分。锁串行化后，第二个进来已看到 fixed，直接早返回。

实现：单进程内存锁，按 session_id 分桶（不同会话互不阻塞）。当前部署是单 uvicorn worker，
足够。**将来多 worker/多机部署**须换成 DB 级锁（如 tutor_sessions.busy 列 + 原子 UPDATE）。

用法：只在**端点层**包一层，绝不在 service 内部再包——threading.Lock 不可重入，
submit_fix（已持锁）内部会调 tutor.run_turn，若 service 再锁会自死锁。
"""

import threading
from contextlib import contextmanager

_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    """取该 session 的锁（首次惰性创建）。dict 的增改用 _guard 保护，防并发建两把锁。"""
    with _guard:
        lk = _locks.get(key)
        if lk is None:
            lk = threading.Lock()
            _locks[key] = lk
        return lk


@contextmanager
def session_turn(session_id: str):
    """进入前独占该会话的回合锁，退出时释放。"""
    lk = _lock_for(session_id)
    lk.acquire()
    try:
        yield
    finally:
        lk.release()
