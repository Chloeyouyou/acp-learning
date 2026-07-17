"""部署期安全门槛。

开发环境允许 subprocess 便于本地调试；显式 ACP_ENV=production 后失败关闭，避免学生代码
在未隔离状态下被公开运行，或因为漏配秘密而带病上线。
"""

from __future__ import annotations

import os

from .services import sandbox


def security_status() -> dict:
    environment = os.environ.get("ACP_ENV", "development").strip().lower() or "development"
    sandbox_choice = os.environ.get("ACP_SANDBOX", "auto").strip().lower() or "auto"
    docker_ready = sandbox.docker_available()
    required_secrets = ("ACP_ADMIN_TOKEN", "ACP_AUTH_SECRET", "DEEPSEEK_API_KEY")
    missing_secrets = [name for name in required_secrets if not os.environ.get(name)]
    production = environment == "production"
    ready = (not production) or (
        sandbox_choice == "docker" and docker_ready and not missing_secrets
    )
    return {
        "environment": environment,
        "production": production,
        "sandbox_config": sandbox_choice,
        "sandbox_backend": sandbox.active_backend(),
        "docker_ready": docker_ready,
        "admin_auth_configured": bool(os.environ.get("ACP_ADMIN_TOKEN")),
        "required_secrets_configured": not missing_secrets,
        "ready": ready,
        # 只报变量名，不返回任何值。
        "missing_configuration": missing_secrets,
    }


def validate_production_environment() -> dict:
    status = security_status()
    if not status["production"]:
        return status

    errors = []
    if status["sandbox_config"] != "docker":
        errors.append("ACP_SANDBOX 必须显式设为 docker")
    if not status["docker_ready"]:
        errors.append("Docker CLI/daemon 不可用，学生代码没有隔离执行边界")
    if status["missing_configuration"]:
        errors.append("缺少生产配置：" + ", ".join(status["missing_configuration"]))
    if errors:
        raise RuntimeError("production_security_gate: " + "；".join(errors))
    return status
