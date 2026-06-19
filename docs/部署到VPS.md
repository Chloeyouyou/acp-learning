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

## 5. 启动
```bash
docker run -d \
  --name acp \
  --restart unless-stopped \
  -p 8000:8000 \
  -e DEEPSEEK_API_KEY="<你的key>" \
  -e DATABASE_URL="sqlite:////data/acp.db" \
  -v /root/acp-data:/data \
  acp-learning
```
说明：
- `--restart unless-stopped`：VPS 重启后自动把它拉起来。
- `-v /root/acp-data:/data` + `DATABASE_URL=.../data/acp.db`：数据库存进 `/root/acp-data`，**容器删了/重建都还在**。
- `-p 8000:8000`：对外开 8000 端口。

检查：
```bash
docker logs acp --tail 20     # 看启动日志
curl http://localhost:8000/api/health   # 返回 {"status":"ok"} 就成功
```

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

## 7. 以后更新代码（数据不会丢）
```bash
cd /root/acp-learning
git pull                       # 拉最新代码
docker build -t acp-learning . # 重新打包
docker rm -f acp               # 删旧容器（数据在 /root/acp-data，不受影响）
# 再执行第 5 步的 docker run ... 重新启动
```

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
