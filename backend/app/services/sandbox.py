"""沙箱运行器（路线 A）。在隔离子进程里真跑学生代码，捕获输出/报错/超时。

复用 validate_patterns.py 验证过的子进程模式。当前本机单用户、跑的是学生自己的代码，
subprocess + 超时 + 输出截断已足够安全；多用户跑不可信代码的真隔离（容器/网络文件限制）
留到路线 D（部署）。
"""

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

OUTPUT_CAP = 8192  # stdout/stderr 各截断上限，防刷屏
DEFAULT_TIMEOUT = 4.0

# 安全：绝不把父进程环境（含 DEEPSEEK_API_KEY 等密钥）灌进学生子进程——否则提交
# `import os; print(os.environ["DEEPSEEK_API_KEY"])` 就能偷走 key。只传跑 Python 所需的最小白名单。
# 同时强制 UTF-8 输出：中文 Windows 下子进程默认 GBK，打印中文会乱码/解码失败。
_ENV_WHITELIST = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "LANG", "LC_ALL")
_UTF8_ENV = {k: os.environ[k] for k in _ENV_WHITELIST if k in os.environ}
_UTF8_ENV.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})


@dataclass
class RunResult:
    returncode: int        # 进程退出码（超时记 -1）
    stdout: str
    stderr: str
    timed_out: bool

    @property
    def has_error(self) -> bool:
        """运行报错：非零退出，或 stderr 里有 traceback。"""
        return self.returncode != 0 or "Traceback (most recent call last)" in self.stderr


def _cap(s: str) -> str:
    if s and len(s) > OUTPUT_CAP:
        return s[:OUTPUT_CAP] + "\n…（输出过长，已截断）"
    return s


def run_code(code: str, timeout: float = DEFAULT_TIMEOUT) -> RunResult:
    """把 code 写临时文件用项目 python 真跑一遍。超时即视为死循环/卡住。"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        tmp = f.name
    try:
        proc = subprocess.run(
            [sys.executable, tmp],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=_UTF8_ENV,
        )
        return RunResult(proc.returncode, _cap(proc.stdout), _cap(proc.stderr), False)
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "replace")
        err = e.stderr if isinstance(e.stderr, str) else (e.stderr or b"").decode("utf-8", "replace")
        return RunResult(-1, _cap(out or ""), _cap(err or ""), True)
    finally:
        Path(tmp).unlink(missing_ok=True)


def normalize_output(s: str) -> str:
    """比对输出前归一化：统一换行、去每行尾随空白、去首尾空行。"""
    lines = (s or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()
