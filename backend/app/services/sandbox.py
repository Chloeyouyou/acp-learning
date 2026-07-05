"""沙箱运行器（路线 A / M1 加固）。在隔离环境里真跑学生代码，捕获输出/报错/超时。

两个后端，接口对外一致（run_code / RunResult / normalize_output 不变）：

- **docker**（默认，公开部署用）：每次运行起一个一次性容器，无网络、只读根、限内存/进程/CPU、
  非 root、丢弃所有 capabilities。学生代码读不到 acp.db、出不了网、fork 炸不了宿主。
- **subprocess**（本地 dev fallback）：老的子进程模式。当前机器没有 docker 时自动降级。
  仅在可信单机开发用——不抗恶意代码，绝不用于公开部署。

用环境变量 ACP_SANDBOX 选后端：docker / subprocess / auto（默认 auto：有 docker 用 docker，否则子进程）。
"""

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

OUTPUT_CAP = 8192  # stdout/stderr 各截断上限，防刷屏
DEFAULT_TIMEOUT = 4.0

# docker 后端参数（公开部署的安全边界，集中一处便于调）
SANDBOX_IMAGE = os.environ.get("ACP_SANDBOX_IMAGE", "python:3.12-slim")
_MEM_LIMIT = "128m"
_PIDS_LIMIT = "64"
_CPUS = "1.0"
# 容器内 GNU timeout 的宽限：比业务超时略大，让容器内先自杀、外层 kill 只兜底
_DOCKER_KILL_GRACE = 5.0

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


@lru_cache(maxsize=1)
def _docker_available() -> bool:
    """docker CLI 在 PATH 且 daemon 可连通。结果缓存——每次运行都探测太慢。"""
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def active_backend() -> str:
    """当前实际生效的后端：docker / subprocess。供 /health 自检和测试用。"""
    choice = os.environ.get("ACP_SANDBOX", "auto").lower()
    if choice == "subprocess":
        return "subprocess"
    if choice == "docker":
        return "docker"  # 显式要 docker：即使探测失败也不静默降级，让 run 时报错暴露配置问题
    return "docker" if _docker_available() else "subprocess"


def run_code(code: str, timeout: float = DEFAULT_TIMEOUT) -> RunResult:
    """把 code 真跑一遍，返回 RunResult。后端由 ACP_SANDBOX 决定（默认 auto）。超时视为死循环/卡住。"""
    backend = active_backend()
    if backend == "docker":
        return _run_docker(code, timeout)
    return _run_subprocess(code, timeout)


def _run_docker(code: str, timeout: float) -> RunResult:
    """一次性隔离容器里跑：无网络、只读根、限内存/进程/CPU、非 root、丢弃 capabilities。

    代码走 stdin 喂给 `python -`（不落宿主文件、不挂卷）。容器内用 GNU coreutils timeout
    先行限时（超时退出码 124），外层 subprocess 超时再 `docker rm -f` 兜底。
    """
    inner = int(timeout) + 1 if timeout > int(timeout) else int(timeout)
    inner = max(inner, 1)
    args = [
        "docker", "run", "--rm", "-i",
        "--network", "none",
        "--memory", _MEM_LIMIT, "--memory-swap", _MEM_LIMIT,
        "--pids-limit", _PIDS_LIMIT,
        "--cpus", _CPUS,
        "--read-only",                       # 根文件系统只读
        "--tmpfs", "/tmp:rw,size=16m",       # 只给一小块可写临时空间（学生代码写文件用）
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", "65534:65534",             # nobody，非 root
        "-e", "PYTHONUTF8=1", "-e", "PYTHONIOENCODING=utf-8",
        SANDBOX_IMAGE,
        "timeout", "--signal=KILL", str(inner), "python", "-I", "-",
    ]
    try:
        proc = subprocess.run(
            args, input=code,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout + _DOCKER_KILL_GRACE,
        )
    except subprocess.TimeoutExpired as e:
        # 外层兜底超时：容器可能还挂着（--rm 未必已清），这里不阻塞返回；孤儿容器由 --rm 最终回收
        out = _decode(e.stdout)
        err = _decode(e.stderr)
        return RunResult(-1, _cap(out), _cap(err), True)
    # 容器内 GNU timeout 杀掉进程时退出码 124/137——归一成 timed_out
    if proc.returncode in (124, 137):
        return RunResult(-1, _cap(proc.stdout), _cap(proc.stderr), True)
    return RunResult(proc.returncode, _cap(proc.stdout), _cap(proc.stderr), False)


def _decode(v) -> str:
    if isinstance(v, str):
        return v
    return (v or b"").decode("utf-8", "replace")


def _run_subprocess(code: str, timeout: float) -> RunResult:
    """本地 dev fallback：把 code 写临时文件用项目 python 真跑。不隔离，仅可信单机用。"""
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
        return RunResult(-1, _cap(_decode(e.stdout)), _cap(_decode(e.stderr)), True)
    finally:
        Path(tmp).unlink(missing_ok=True)


def normalize_output(s: str) -> str:
    """比对输出前归一化：统一换行、去每行尾随空白、去首尾空行。"""
    lines = (s or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()
