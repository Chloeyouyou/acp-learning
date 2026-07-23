# 2026-07-23 VPS 升级到最新版 + 修复沙箱运行 500(docker-cli)

运维/修 bug 一场,非里程碑开发。VPS `root@72.11.133.118`。
完整排查记录另存 `docs/升级到最新版-实操清单.md`「踩过的坑」节;权威升级流程仍以 `docs/部署到VPS.md` §7 为准。

## 背景

按 §7 把 VPS 升级到最新版(git pull + rebuild + 用本地 `backend/acp.db` 覆盖数据卷)。
升级后登录正常、`stu_n6ooz8` 能进,但学生点「运行」报 `运行失败:请求失败 (500)`。

## 定位过程

- 先排掉两个虚惊:**不是数据问题**(scp 上去的本地库 alembic 已在 head `d8a4d2cf8080`,schema 与新代码对齐,`stu_n6ooz8` 数据都在)、**不是 AI key / schema 漂移**(跑代码链 `run_and_inject` 根本不调 DeepSeek)。
- 锁定在沙箱:`ACP_SANDBOX="docker"` 强制不静默降级 → `sandbox._run_docker` 里 `subprocess.run(["docker", ...])` 一旦失败就抛异常 → HTTP 500(普通的 docker 跑失败只会当运行输出返回,不会 500;能 500 说明是真异常)。
- 决定性一步:`docker exec acp docker run --rm python:3.12-slim ...` → `exec: "docker": executable file not found in $PATH`。**acp 容器里没有 docker 客户端命令。**

## 根因(重要)

base 镜像 `python:3.12-slim` 已悄悄升到 **Debian 13 (trixie)**。trixie 把 `docker.io` 拆包:
- `docker.io` = 仅 daemon(dockerd)
- **`docker-cli`** = 客户端 `docker` 命令

Dockerfile 里 `apt-get install docker.io` 在 trixie 上**安装成功但只装了 dockerd**,没有 `docker` 客户端 →
`ACP_SANDBOX=docker` 时容器内 `docker run` 找不到命令 → 500。
现场验证过:干净 base 里装 `docker.io` 后 `command -v docker` 为空;改装 `docker-cli` 则有 `/usr/bin/docker`(26.1.5)。

`--no-cache` 重 build 也没用——不是缓存问题,是包本身不含客户端。

## 修复

- Dockerfile 那行 `docker.io` → `docker-cli`(只需客户端,daemon 用宿主的,还更省体积)。
  commit `06dfa90`,已 push `main`;本地/VPS/GitHub 三边 fast-forward 对齐。
- VPS 重 build + 重起容器后验收通过:
  - `docker exec acp docker run --rm python:3.12-slim python -c "print('sandbox ok')"` → `sandbox ok`
  - `curl localhost:8000/api/health` → `{"status":"ok","sandbox":"docker","security_ready":true,...}`
  - **真隔离生效**,浏览器点「运行」不再 500。

## 顺手踩到的小坑(记着别再犯)

- `printenv` 后面跟**变量名** `DEEPSEEK_API_KEY`,不是 key 的值。写成值会让 `KEY=$(...)` 取空 → 新容器没 key → 导师对话挂。重起时把 key 直接写进 `-e DEEPSEEK_API_KEY="sk-..."`。
- SSH 掉线(`Connection reset`)后命令会落到本机 PowerShell 上跑,全部失败(Docker Desktop 没起、`\` 不是 PS 的换行符)。认提示符:`root@racknerd...#`=在 VPS;`PS C:\...>`=在本机。多行命令压成单行更抗掉线。

## 待办

- **换 DeepSeek key**:`sk-6cf8...` 本次排查中在对话里露过明文,方便时控制台轮换、`docker rm -f acp` 后用新 key 重跑启动。
- 老库登录 500 那个 `db.py:init_db` stamp 分支 bug 仍未在代码层修(本次因用的是新结构库,没踩到)。
