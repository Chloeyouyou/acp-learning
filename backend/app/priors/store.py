"""每个学生一个 JSON 文件的先验存储——独立命名空间，不进宿主数据库。

人类可读可纠正是硬需求：打开文件能看懂每条先验、它的证据来自哪几次经历；
手动删掉一条错误先验即生效。迁移 = 整个目录搬走。
"""

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Evidence:
    """一条通用证据：宿主把自己的记录（经历/对话摘要）转成这个形状喂进来。"""

    text: str
    source_id: str   # 来源标识（如会话 id）——3 证据门槛按它去重
    at: str          # ISO 时间


def empty_data(student_id: str) -> dict:
    return {"student_id": student_id, "priors": [], "candidates": [], "transient": []}


# 文件名只允许安全字符，防路径穿越（student_id 来自宿主，不默认可信）。
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class PriorStore:
    def __init__(self, dir_path):
        self.dir = Path(dir_path)

    def _path(self, student_id: str) -> Path:
        if not _SAFE_ID_RE.match(student_id or ""):
            raise ValueError(f"unsafe student_id: {student_id!r}")
        return self.dir / f"{student_id}.json"

    def load(self, student_id: str) -> dict:
        """读档；不存在给空骨架。临时态过期即弃（TTL 清理发生在读取时）。"""
        path = self._path(student_id)
        if not path.exists():
            return empty_data(student_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in ("priors", "candidates", "transient"):
            data.setdefault(key, [])
        now = utcnow_iso()
        data["transient"] = [t for t in data["transient"] if t.get("expires_at", "") > now]
        return data

    def save(self, student_id: str, data: dict) -> None:
        """原子写：先写临时文件再替换，进程中途死掉也不会留半个 JSON。"""
        path = self._path(student_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
