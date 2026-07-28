# 协作工作台 MVP

这是面向售前与解决方案团队的轻量协作工作台。系统以统一项目主数据为骨架，将任务、工作
记录和 AI 周报关联到可信的项目上下文中。

当前阶段不实现工作台首页或图表展示。

## 工程结构

```text
app/                 FastAPI 应用与领域服务
alembic/             数据库迁移
docs/                当前产品、接口与阶段说明
frontend/            React 19 + Vinext 前端
tests/               后端自动化测试
.env.example         后端配置模板
pyproject.toml        Python 依赖与工具配置
server.py             本地/内网启动入口
```

运行数据库、模型密钥、缓存、原始头像和旧原型均为本地文件，不进入 Git。系统实际使用的
头像是 `frontend/public/avatars/` 中经过压缩和校验的 WebP。

当前阶段边界与交付检查见 [MVP 阶段说明](docs/MVP_RELEASE.md)，接口及权限契约见
[API 契约](docs/API_CONTRACT.md)。

## 已实现

- 本地独立账号、服务端 Session、CSRF 和固定角色权限。
- 项目标签；初始标签为“商机”和“改造”。
- 项目父子层级，标签与层级相互独立。
- 项目建议、状态流转、负责人、成员和时间范围。
- 项目标准名称、别名、精确查重和模糊重复提示。
- 项目合并预览及事务化合并。
- 基础任务、分派/转派、阻塞、完成和取消规则。
- 工作记录、待归集、任务反向推导项目和产出物链接。
- 全角色个人设置、本人密码修改和系统预置头像选择。
- `revision` 乐观锁、软删除和操作审计。
- SQLite WAL、外键约束、Alembic 迁移和一致性在线备份。

## 本地安装

需要 Python 3.12 或更高版本以及 `uv`。

```powershell
uv sync --all-groups
Copy-Item .env.example .env
uv run python -m app.cli upgrade-db
```

创建应急超级管理员：

```powershell
uv run python -m app.cli create-user developer "开发者" --role super_admin
```

命令会安全地提示输入初始密码。超级管理员不可以通过业务 API 创建。

启动开发服务。默认端口由 `.env` 中的 `MVP_SERVER_PORT` 控制，前端开发端口固定为
`5174`，后端默认使用 `8787`：

```powershell
uv run python server.py --reload
```

如本机 `8787` 被其他固定服务占用，可在 `.env` 中修改 `MVP_SERVER_PORT`，并同步修改前端
API Base URL；命令行参数 `--port` 可用于单次覆盖。

受控内网试运行时，将 `.env` 中的 `MVP_ALLOWED_HOSTS_CSV` 设置为服务器 IP，并运行：

```powershell
uv run python server.py --host 0.0.0.0 --port 8787
```

API 文档位于：

```text
http://服务器IP:8787/docs
```

前端启动：

```powershell
Set-Location frontend
npm install
npm run dev
```

本地地址为 `http://127.0.0.1:5174`。内网部署时需要同时调整前端
`NEXT_PUBLIC_API_BASE_URL`、后端 `MVP_ALLOWED_HOSTS_CSV` 和 `MVP_CORS_ORIGINS_CSV`。

## 大模型 AI

系统管理员和超级管理员可在“系统设置 → 大模型接入”中配置 DeepSeek、GLM、
Kimi 或 MiniMax。连接测试会发送一条最小请求并消耗少量 Token；只有测试通过后，
同一组服务商、模型和 API Key 才能写入系统配置。

MiniMax 需要额外选择接入方式：

- `Token Plan`：使用 `sk-cp-` 开头的 Token Plan Key，通过
  `https://api.minimaxi.com/anthropic` 的 Anthropic 兼容协议接入。连接测试会占用一次
  Token Plan 请求额度。
- `按量计费`：使用开放平台普通 API Key，通过
  `https://api.minimaxi.com/v1` 的 OpenAI 兼容协议接入，按实际 Token 计费。

两类 Key 不可互换；后端会在发起厂商请求前校验密钥类型，避免走错计费链路。

浏览器不会保存或回显模型密钥。API Key 由后端加密后存入数据库，部署时必须在未提交的
`.env` 中配置独立的高强度加密密钥：

```text
MVP_LLM_CONFIG_SECRET=使用密码管理器生成的高熵随机值
MVP_LLM_TIMEOUT_SECONDS=60
MVP_LLM_TEST_TOKEN_TTL_SECONDS=600
```

该主密钥必须与数据库备份一起保管；丢失或更换后，已保存的 API Key 将无法解密，需要管理员重新测试并配置。

原有 `MVP_MINIMAX_*` 环境变量只作为升级期间的兼容回退；通过设置页保存后，数据库配置
优先。`MVP_MINIMAX_ACCESS_MODE=auto` 会根据 `sk-cp-` 前缀自动选择 Token Plan，
也可显式设置为 `token_plan` 或 `pay_as_you_go`。前端仅调用工作台自己的 AI 接口，
AI 建议不会自动修改业务数据。

## 初始化业务账号

先通过服务器命令创建第一个系统管理员：

```powershell
uv run python -m app.cli create-user admin "系统管理员" --role system_admin
```

系统管理员和超级管理员登录后可以通过 `POST /api/v1/users` 创建其他账号；创建时只填写
姓名、角色和初始密码，登录名由系统自动生成并在创建结果中展示。普通用户首次登录后必须
修改初始密码。
登录会话默认12小时失效，可通过 `MVP_SESSION_TTL_HOURS` 调整；失效后浏览器会自动返回登录页。

所有角色都可以在“个人设置”中修改自己的密码和选择系统头像。系统不接受头像上传或外部
图片地址；头像文件及命名规则见 `frontend/public/avatars/README.md`。

## 数据库迁移

```powershell
uv run alembic upgrade head
uv run alembic current
```

应用启动不会隐式创建表或修改业务数据；部署前必须显式执行迁移。

## 在线备份

备份命令使用 SQLite Online Backup API，并在完成后执行 `PRAGMA integrity_check`：

```powershell
uv run python -m app.backup --output-dir "E:\approved-mvp-backups"
```

每次备份生成：

- 一致的 `.db` 快照；
- 包含 SHA-256、文件大小、表数量和 schema revision 的校验清单。

试运行环境应由操作系统计划任务每天调用一次，并把输出目录设置为异机或公司批准的备份位置。

## 测试

```powershell
uv run pytest
uv run pytest --cov=app --cov-report=term-missing
```

测试覆盖账号鉴权、权限、标签与层级、查重、别名、循环检测、项目合并、任务状态、工作记录关联和审计。

## 重要试运行限制

- IP＋端口 HTTP 只用于受控 MVP 试运行。
- 使用专门测试密码，不复用公司账号密码。
- 防火墙只允许试点网段或明确设备访问。
- 单应用实例运行，不要启动多个 worker 共享同一个 SQLite。
- 数据库必须放在服务器本机磁盘，不放在 SMB、NAS 或同步盘。
- 正式推广前必须切换 HTTPS，并把 `MVP_COOKIE_SECURE` 设置为 `true`。
