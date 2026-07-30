# systemd 部署

这套配置以两个独立进程运行 MVP：

- `solution-workspace-backend.service`：FastAPI，仅监听 `127.0.0.1:8787`，由前端同源转发。
- `solution-workspace-frontend.service`：Vinext，监听 `0.0.0.0:5174`。
- `solution-workspace.target`：统一启停前后端。

服务默认使用 `appuser`，安装脚本会把实际工程路径写入 unit，因此工程目录名可以自定义。

## 1. 准备运行环境

以下操作使用 `appuser` 执行。假设工程位于
`/home/appuser/solution-department-weekly-report`：

```bash
cd /home/appuser/solution-department-weekly-report

uv sync --frozen --no-dev
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，至少确认：

```dotenv
MVP_ENVIRONMENT=production
MVP_DATABASE_URL=sqlite:///./data/mvp.db
MVP_SERVER_HOST=127.0.0.1
MVP_SERVER_PORT=8787
MVP_COOKIE_SECURE=false
MVP_ALLOWED_HOSTS_CSV=服务器IP,127.0.0.1,localhost
MVP_CORS_ORIGINS_CSV=
MVP_LLM_CONFIG_SECRET=使用密码管理器或openssl生成的高熵随机值
```

当前 IP＋端口试运行使用 HTTP，所以 `MVP_COOKIE_SECURE=false`。切换 HTTPS 后必须改为
`true`。可以使用下面的命令生成模型配置加密主密钥：

```bash
openssl rand -hex 32
```

准备前端。浏览器只访问同源 `/api`，前端服务在服务器内部转发到后端：

```bash
cd /home/appuser/solution-department-weekly-report/frontend
cp .env.example .env.local
npm ci
npm run build
```

## 2. 安装服务

安装 unit 需要 root 权限；业务进程仍然以 `appuser` 运行：

```bash
cd /home/appuser/solution-department-weekly-report
sudo bash ./deploy/systemd/install.sh "$PWD" appuser
```

如果 Node.js 通过 nvm 安装且脚本没有自动找到 `node`，把绝对路径作为第三个参数：

```bash
sudo bash ./deploy/systemd/install.sh "$PWD" appuser /home/appuser/.nvm/versions/node/v22.13.0/bin/node
```

安装器会执行以下操作：

- 验证 `.env`、Python 虚拟环境、前端依赖和生产构建；
- 创建并授权 `data/`、`backups/`；
- 将 `.env` 权限收紧为 `0600`；
- 安装并通过 `systemd-analyze verify` 校验 unit，然后执行 `daemon-reload` 并启动前后端；
- 后端每次启动前自动执行 `alembic upgrade head`。

## 3. 日常运维

```bash
# 查看状态
sudo systemctl status solution-workspace.target
sudo systemctl status solution-workspace-backend.service
sudo systemctl status solution-workspace-frontend.service

# 查看日志
sudo journalctl -u solution-workspace-backend.service -f
sudo journalctl -u solution-workspace-frontend.service -f

# 统一重启或停止
sudo systemctl restart solution-workspace.target
sudo systemctl stop solution-workspace.target
sudo systemctl start solution-workspace.target
```

## 4. 更新版本

```bash
cd /home/appuser/solution-department-weekly-report
git pull --ff-only
uv sync --frozen --no-dev

cd frontend
npm ci
npm run build

cd ..
sudo bash ./deploy/systemd/install.sh "$PWD" appuser
```

## 5. 网络边界

在服务器防火墙中只向试点内网网段开放 TCP `5174`，不要直接暴露到公网。后端
`8787` 仅监听回环地址，不对内网终端开放。
数据库、`.env` 和 `backups/` 不应由任何静态文件服务提供。
