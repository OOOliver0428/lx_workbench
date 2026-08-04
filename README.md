# 解决方案团队协作工作台

面向售前与解决方案团队的轻量协作系统，把商机推进、项目执行、任务协同、工作记录、周报和
AI 辅助放在同一个工作台中。

> 当前版本：**0.1.0** · 发布基线：`mvp` · 状态：可进入受控试运行部署

[查看更新日志](CHANGELOG.md) · [Ubuntu 部署与运维](docs/UBUNTU_DEPLOYMENT.md) ·
[版本发布规范](docs/RELEASING.md) · [API 契约](docs/API_CONTRACT.md)

## 核心业务闭环

```text
商机追踪 → 方案交流 → 转为项目 → 项目/任务执行 → 工作记录 → 个人/团队周报
                                      └──────────────→ AI 助手
```

- **商机追踪**：商机清单、关系图、追加式推进记录，以及方案交流阶段一键预填创建项目。
- **作战台**：自然周视角的工作管理、跨周趋势、提交矩阵、阶段时间线和团队周报。
- **项目与任务**：标签、父子层级、成员、状态流转、查重、合并、分派、阻塞和跨项目关联。
- **工作记录与周报**：待归集、项目/任务关联、本周筛选、个人周报和基于已提交周报的团队汇总。
- **AI 能力**：支持 DeepSeek、GLM、Kimi、MiniMax；密钥由后端加密保存，AI 结果不会自动修改业务数据。
- **权限体系**：按功能递增授权，商机、项目、任务、作战台、工作记录、周报和系统设置相互隔离。
- **安全与审计**：本地账号、服务端 Session、CSRF、乐观锁、软删除和操作审计。

## 0.1.0 运行基线

| 项目 | 当前基线 |
|---|---|
| 后端 | Python 3.12、FastAPI、SQLAlchemy、Alembic |
| 前端 | Node.js ≥ 22.13、React 19、Vinext |
| 数据库 | 单节点本机 SQLite，WAL、外键约束、在线一致性备份 |
| Ubuntu 入口 | 前端 `0.0.0.0:5174` |
| 内部 API | 后端 `127.0.0.1:8787`，只由前端同源代理访问 |
| 部署范围 | Ubuntu 22.04/24.04 LTS 受控内网或 VPN 单节点试运行 |

生产拓扑：

```text
浏览器
  │ HTTP/HTTPS :5174
  ▼
Vinext 前端 ── 同源 /api ──► FastAPI :8787 ──► 本机 SQLite
                                  │
                                  └──────────► 大模型厂商 HTTPS API
```

## 本地开发

### 环境要求

- Python 3.12 或更高版本；
- [`uv`](https://docs.astral.sh/uv/)；
- Node.js 22.13 或更高版本；
- npm。

### 后端

```powershell
uv sync --all-groups
Copy-Item .env.example .env
uv run python -m app.cli upgrade-db
uv run python -m app.cli create-user admin "系统管理员" --role system_admin
uv run python server.py --reload
```

创建用户命令会安全提示输入密码。后端默认访问地址为 `http://127.0.0.1:8787`。

### 前端

```powershell
Set-Location frontend
npm ci
npm run dev
```

前端默认访问地址为 `http://127.0.0.1:5174`。浏览器只访问同源 `/api`，前端服务内部通过
`MVP_INTERNAL_API_BASE_URL` 转发到后端。

Windows 联调推荐使用统一脚本，它会启动前后端、执行迁移、检查端口并等待健康检查：

```powershell
.\scripts\windows-test.cmd start
.\scripts\windows-test.cmd status
.\scripts\windows-test.cmd stop
```

端口冲突时可以自动选择可用端口：

```powershell
.\scripts\windows-test.cmd start -AutoSelectPorts
```

### 演示数据

测试数据库可写入覆盖主要功能和权限组合的演示数据：

```powershell
uv run python -m app.cli seed-demo-data --password "Demo-Password-2026!"
```

账号与场景说明见 [演示数据手册](docs/DEMO_DATA.md)。

## Ubuntu 一键部署

首次安装：

```bash
git clone --branch mvp --single-branch https://github.com/OOOliver0428/lx_workbench.git
cd lx_workbench
sudo bash deploy/ubuntu/install.sh --public-host 服务器IP或内网域名
sudo solution-workspace create-admin admin "系统管理员"
sudo solution-workspace health
sudo solution-workspace backup
```

浏览器访问 `http://服务器IP:5174/`。部署脚本会安装锁定依赖、构建前端、迁移数据库、安装
systemd 服务，并启用每日备份 timer。

日常运维：

```bash
sudo solution-workspace status
sudo solution-workspace health
sudo solution-workspace logs backend 200
sudo solution-workspace logs frontend 200
sudo solution-workspace backup
sudo solution-workspace db-info
```

从 GitHub 正常更新：

```bash
sudo solution-workspace update origin mvp
sudo solution-workspace health
sudo systemctl is-enabled solution-workspace-backup.timer
sudo systemctl is-active solution-workspace-backup.timer
```

服务器无法稳定连接 GitHub 时，可以在可信电脑制作增量 Git bundle，再通过 SCP、堡垒机或批准介质
传入服务器。bundle 只携带代码，不等于完全离线依赖包。完整的首次部署、bundle 更新、版本感知
回滚、备份恢复、试用库切正式库和故障排查步骤见
[Ubuntu 部署与运维手册](docs/UBUNTU_DEPLOYMENT.md)。

## 数据库与试用期切换

首次 Ubuntu 部署默认使用：

```dotenv
MVP_DATABASE_URL=sqlite:////var/lib/solution-workspace/trial.db
```

试用期结束有三种受控方案：

- 新建空正式库，不保留试用数据；
- 冻结并克隆试用库，完整提升为正式库；
- 校验外部 SQLite 文件后切换。

不要在应用运行时手工覆盖 `.db`、`.db-wal` 或 `.db-shm`。应使用
`solution-workspace switch-db` 或 `promote-db`，并在维护窗口完成备份、健康检查和业务对账。
具体步骤见[试用库与正式库切换](docs/UBUNTU_DEPLOYMENT.md#5-试用库与正式库切换)。

`MVP_LLM_CONFIG_SECRET` 不随数据库切换而改变；它与数据库备份必须一起保管，否则数据库中已经保存的
大模型 API Key 将无法解密。

## AI 配置与网络说明

拥有“大模型配置”权限的管理员可在“系统设置 → 大模型接入”中完成连接测试和保存。浏览器不会保存
或回显 API Key，后端使用 `MVP_LLM_CONFIG_SECRET` 加密后写入数据库。

- HTTP 内网试运行设置 `MVP_COOKIE_SECURE=false`；0.1.0 已兼容非安全上下文下的 AI 消息 ID 生成。
- 上线 HTTPS 后设置 `MVP_COOKIE_SECURE=true`，并重新验证登录、Session、CSRF 和同源 `/api`。
- AI 配置测试成功只证明最小请求可用；单次聊天失败时还需检查 `/api/v1/ai/chat` 响应中的
  `details.provider_status`，不要仅凭页面通用提示判断是额度问题。

AI 网络和厂商错误的安全排查方法见
[AI 功能故障排查](docs/UBUNTU_DEPLOYMENT.md#ai-功能异常)。

## 权限基线

- 新账号默认拥有项目只读、任务只读、工作记录全部功能、个人周报全部功能、AI 助手和个人设置。
- 商机权限按“查看 → 录入进展 → 新建商机”递增。
- 项目、任务权限按“查看 → 编辑 → 创建”递增，高级权限自动包含低级权限。
- 工作管理按“查看 → 生成团队周报”递增，仅对至少为团队负责人且有有效直属成员的账号生效。
- 超级管理员拥有全部权限但不进入业务用户候选目录；个人周报始终只对作者本人可见。

详细接口和权限边界以 [API 契约](docs/API_CONTRACT.md) 为准。

## 测试

```powershell
uv run ruff check app tests
uv run pytest

Set-Location frontend
npm run lint
npm test
```

CI 同时执行后端测试、前端构建/渲染测试，以及 Ubuntu 部署脚本和 systemd 模板校验。

## 工程结构

```text
app/                 FastAPI 应用、领域服务和 CLI
alembic/             数据库迁移
deploy/              Ubuntu 安装、运维脚本和 systemd 模板
docs/                产品、接口、部署和版本文档
frontend/            React 19 + Vinext 前端
scripts/             本地联调脚本
tests/               后端及部署资产自动化测试
.github/workflows/    GitHub Actions CI
```

运行数据库、备份、日志、模型密钥、缓存、旧原型和离线 bundle 均不进入 Git。

## 文档导航

| 文档 | 用途 |
|---|---|
| [CHANGELOG.md](CHANGELOG.md) | 当前版本、未发布变更和历次更新日志 |
| [docs/RELEASING.md](docs/RELEASING.md) | 版本号、更新日志、标签和发布步骤 |
| [docs/UBUNTU_DEPLOYMENT.md](docs/UBUNTU_DEPLOYMENT.md) | 部署、升级、回滚、备份、切库和故障排查 |
| [docs/MVP_RELEASE.md](docs/MVP_RELEASE.md) | 0.1.0 MVP 范围和交付边界 |
| [docs/API_CONTRACT.md](docs/API_CONTRACT.md) | API、权限和安全契约 |
| [docs/DEMO_DATA.md](docs/DEMO_DATA.md) | 演示账号和功能覆盖数据 |
| [docs/PRODUCT_REQUIREMENTS_V2.md](docs/PRODUCT_REQUIREMENTS_V2.md) | 当前产品需求基线 |

## 版本与更新日志

当前发布基线为 **0.1.0**。从下一次迭代开始，每个影响用户、部署、配置、数据库、安全或兼容性的
变更，都必须先写入 [CHANGELOG.md](CHANGELOG.md) 的 `Unreleased`；发布时再归档到对应版本，并同步
后端、前端和锁文件中的版本号。项目采用语义化版本，完整规则见
[版本发布规范](docs/RELEASING.md)。

## 试运行限制

- IP＋端口 HTTP 只用于受控内网或 VPN 试运行，不直接暴露公网。
- 防火墙和云安全组只允许批准网段访问前端 `5174`，后端 `8787` 不对终端开放。
- 使用独立测试密码，不复用公司统一身份密码。
- 只运行一个应用实例，不启动多个 worker 共享 SQLite。
- 数据库放在服务器本机固定磁盘，不放在 NAS、SMB、NFS 或同步盘。
- 本机 `/var/backups` 不是完整灾备，必须配置异机复制和恢复演练。
- 正式推广前必须启用 HTTPS，并重新进行容量、备份恢复和安全评审。
