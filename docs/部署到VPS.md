# 把 ACP Learning 部署到自己的 VPS

面向零基础。用 Docker（仓库已自带 Dockerfile，一键打包前后端），数据存在 VPS 磁盘上**永不丢**。
全程在 VPS 的终端里复制粘贴。假设系统是 Ubuntu/Debian。

> 名词：`<...>` 是要你替换成自己值的占位符。`#` 开头是注释，不用敲。

---

## 0. 准备
- 一台 VPS（1 核 / 1G 内存起步够内测），有 root 的 SSH 登录。
- 你的 `DEEPSEEK_API_KEY`。
- GitHub 上的私有仓库 `Chloeyouyou/acp-learning`，以及一个 **Personal Access Token (PAT)**
  （GitHub → Settings → Developer settings → Personal access tokens → 生成一个，勾 `repo` 权限）。

SSH 登录 VPS：
```bash
ssh root@<你的VPS_IP>
```

## 1. 装 Docker（一次性）
```bash
curl -fsSL https://get.docker.com | sh
docker --version    # 能打印版本号就装好了
```

## 2. 把代码拉到 VPS
```bash
cd /root
# 用 PAT 克隆私有仓库（把 <PAT> 换成你的 token）
git clone https://<PAT>@github.com/Chloeyouyou/acp-learning.git
cd acp-learning
```

## 3. 建一个"数据目录"（让数据库存在 VPS 上，重建容器也不丢）
```bash
mkdir -p /root/acp-data
```

## 4. 打包镜像
```bash
cd /root/acp-learning
docker build -t acp-learning .
# 第一次会下载/编译，几分钟。出现 "naming to ... acp-learning" 就是成功
```

## 4.5 预拉沙箱镜像（学生代码在隔离容器里跑，一次性）
学生每次点「运行」，系统会起一个一次性隔离容器（无网络、只读、限内存）跑他的代码——
读不到数据库、出不了网、炸不了 VPS。这需要一个 Python 镜像，先拉好省得首次运行现拉：
```bash
docker pull python:3.12-slim
```

## 5. 启动
```bash
docker run -d \
  --name acp \
  --restart unless-stopped \
  -p 8000:8000 \
  -e DEEPSEEK_API_KEY="<你的key>" \
  -e DATABASE_URL="sqlite:////data/acp.db" \
  -e ACP_SANDBOX="docker" \
  -v /root/acp-data:/data \
  -v /var/run/docker.sock:/var/run/docker.sock \
  acp-learning
```
说明：
- `--restart unless-stopped`：VPS 重启后自动把它拉起来。
- `-v /root/acp-data:/data` + `DATABASE_URL=.../data/acp.db`：数据库存进 `/root/acp-data`，**容器删了/重建都还在**。
- `-p 8000:8000`：对外开 8000 端口。
- `-e ACP_SANDBOX="docker"` + `-v /var/run/docker.sock:/var/run/docker.sock`：**开启沙箱真隔离**。
  让容器能调宿主 docker 起一次性子容器跑学生代码。**公开给学生前这两行必须有**——
  否则学生代码在主容器里裸跑，能读全班数据库。不挂 socket 时系统会自动降级成不隔离的
  subprocess 模式（仅适合你自己单机测），`/api/health` 会显示 `"sandbox":"subprocess"` 提醒你。

检查：
```bash
docker logs acp --tail 20     # 看启动日志
curl http://localhost:8000/api/health   # 返回 {"status":"ok","sandbox":"docker"} 才算隔离生效
```
> 若 `sandbox` 显示 `subprocess`，说明 socket 没挂上或宿主 docker 没起——学生代码此时**未隔离**，
> 先别对外放学生，排查 `-v /var/run/docker.sock` 和 `docker info` 是否正常。

浏览器打开 `http://<你的VPS_IP>:8000` —— 能看到首页就跑起来了。

## 6. 加 HTTPS（推荐，可稍后）
`http://IP:8000` 能用，但没加密、手机上某些功能受限。三选一：

- **A. 有域名 + Caddy（最省心，自动证书）**：把域名 A 记录指向 VPS IP，然后
  ```bash
  # 安装 caddy 后，/etc/caddy/Caddyfile 写：
  你的域名 {
      reverse_proxy localhost:8000
  }
  ```
  Caddy 会自动签 HTTPS 证书。
- **B. Cloudflare Tunnel**（你之前用过 cloudflared）：在 VPS 上跑 `cloudflared tunnel`
  指向 `localhost:8000`，拿到一个 https 公网地址，连端口都不用对外开。
- **C. 先不加**：内测同学少、先用 `http://IP:8000` 验证功能也行。

## 7. 以后更新到最新版（权威流程 · 数据不丢）

> 这是 VPS 已经跑过一版、要升级到 GitHub 最新代码时的**标准步骤**。本机 VPS：`root@72.11.133.118`。
> 一步一步来，某步报红色错误就停下，别往下敲。

**第 0 步 · 连上 VPS**
自己电脑开 PowerShell（Win 键 → 输 `powershell` → 回车）：
```bash
ssh root@72.11.133.118
```
输 root 密码（屏幕不显示字是正常的）。成功 = 提示符变成 `root@...:~#`。
> 若反复 `Connection closed` / 握手超时 → 国内线路掐 22 端口，走 RackNerd 网页控制台（VNC）操作，或换 SSH 端口。
> 建议装一次免密公钥，之后 ssh/scp 不再要密码：把本机 `~/.ssh/id_ed25519.pub` 内容 append 到 VPS 的 `~/.ssh/authorized_keys`。

**第 1 步 · 先抄下 AI 的 key（等下重启要用）**
```bash
docker exec acp printenv DEEPSEEK_API_KEY
```
打印的 `sk-...` 字符串复制存好。

**第 2 步 · 拉最新代码**
```bash
cd /root/acp-learning
git pull
```
成功 = 文件名滚过、无红色报错。若要账号密码 → GitHub 令牌过期，先停下。

**第 3 步 · 预拉沙箱镜像（学生代码隔离运行用）**
```bash
docker pull python:3.12-slim
```

**第 4 步 · 重新打包（几分钟）**
```bash
docker build -t acp-learning .
```
成功 = 最后出现 `naming to ... acp-learning`。

**第 5 步 · 删旧容器（数据在 `/root/acp-data`，不受影响）**
```bash
docker rm -f acp
```

**第 6 步 · 启动新版（整行一次性粘贴，把 `<你的key>` 换成第 1 步抄的）**
```bash
docker run -d --name acp --restart unless-stopped -p 8000:8000 -e DEEPSEEK_API_KEY="<你的key>" -e DATABASE_URL="sqlite:////data/acp.db" -e ACP_SANDBOX="docker" -v /root/acp-data:/data -v /var/run/docker.sock:/var/run/docker.sock acp-learning
```
成功 = 打印一长串容器 ID。

**第 7 步 · 验收**
```bash
curl http://localhost:8000/api/health
```
必须看到 `"status":"ok"` 且 `"sandbox":"docker"`（后者=安全隔离生效）。显示 `subprocess` 说明 socket 没挂上，排查第 6 步的 `-v /var/run/docker.sock`。
最后浏览器开 `http://72.11.133.118:8000`，看到浅色新 UI + 「课程地图」入口即成功。

> ⚠️ **老库升级坑（已知）**：若 VPS 上是「登录功能之前」的老库（没有 `students` 表），新版启动的自动纳管会跳过建表 → 登录报 500。
> 处置：老库测试数据不要了就 `docker stop acp && rm -f /root/acp-data/acp.db*  && docker start acp`（重建全新库）；
> 要保留本地进度就把本地 `backend/acp.db`（已是新版结构）`scp` 覆盖上去再 `docker start acp`。此 bug 待在代码层修 `db.py:init_db` 的 stamp 分支。

## 8. 备份数据（养成习惯）
数据库就是一个文件，定期拷走即可：
```bash
cp /root/acp-data/acp.db /root/acp-backup-$(date +%F).db
```
（从 VPS 下载到本地：在你自己电脑上 `scp root@<IP>:/root/acp-data/acp.db .`）

---

## 常见问题
- **8000 打不开**：VPS 防火墙/安全组要放行 8000 端口（云服务商控制台里设）。
- **改了 key/环境变量**：`docker rm -f acp` 后用新值重跑第 5 步。
- **看运行状态**：`docker ps`（在跑的容器）、`docker logs acp`（日志）。
- ⚠️ **安全**：VPS 上是用 subprocess 跑学生代码，**信任的同学内测够用**；
  对外公开前要上容器隔离/限网（路线图"完整 D"）。
