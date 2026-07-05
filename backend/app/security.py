"""轻量身份 token（M1 D2-3）。

无密码、无状态：登录只需学号，服务端用 HMAC 给学号签一个 token。之后每次请求带 token，
服务端从 token 里取出学号（校验签名），**不再信任 URL/请求体里自报的学号**——这样就堵死了
「改 URL 遍历别人数据」的越权（IDOR）。

档位说明（方案 A，已拍板）：这挡住外部随机遍历/脱库，但挡不住「知道你学号的同学登录成你」——
学号本就班内半公开，冒充看学习画像无实质收益，不值得用记密码的摩擦去防。将来要防冒充，
在 login 端点加一步 PIN 校验即可，token 层不动。

token 格式：`<b64url(student_id)>.<hex(hmac_sha256(secret, b64url(student_id))[:16])>`
无状态：不落库、服务器重启后旧 token 仍有效（只要 secret 不变）。
"""

import base64
import hashlib
import hmac
import os
import secrets

from .config import BASE_DIR

_SECRET_FILE = BASE_DIR / ".auth_secret"


def _load_secret() -> bytes:
    """签名密钥：优先环境变量 ACP_AUTH_SECRET；否则在 BASE_DIR 生成并持久化一份随机密钥。

    持久化（而非每次启动随机）是为了让已签发的 token 跨重启仍有效。文件已 gitignore、
    VPS 上落在数据卷里。绝不硬编码默认密钥——否则谁都能伪造 token 冒充任意学号。
    """
    env = os.environ.get("ACP_AUTH_SECRET")
    if env:
        return env.encode("utf-8")
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_bytes()
    token = secrets.token_bytes(32)
    _SECRET_FILE.write_bytes(token)
    return token


_SECRET = _load_secret()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(payload: str) -> str:
    return hmac.new(_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def sign_token(student_id: str) -> str:
    """给学号签发一个 token。"""
    payload = _b64(student_id.encode("utf-8"))
    return f"{payload}.{_sign(payload)}"


def verify_token(token: str | None) -> str | None:
    """校验 token，返回其中的学号；无效返回 None（常量时间比较防时序侧信道）。"""
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        return _unb64(payload).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
