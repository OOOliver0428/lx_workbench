# Ubuntu 部署与运维手册

本文适用于 `mvp` 分支当前架构：Ubuntu 单节点、单应用实例、本机 SQLite、前端同源代理后端。
试运行期间可使用独立试用库；业务确认后可切换到新的正式库，或者把试用数据完整提升为正式库。

## 1. 部署边界

- 推荐 Ubuntu 22.04/24.04 LTS，服务器需要能访问 Ubuntu、NodeSource、Astral 和 npm 软件源。
- Node.js 最低版本为 22.13，Python 由 `uv` 固定为 3.12。
- 前端默认监听 `0.0.0.0:5174`，只应向批准的公司内网或 VPN 网段开放。
- 后端默认只监听 `127.0.0.1:8787`，浏览器不能直接访问后端端口。
- SQLite 主库必须放在 `/var/lib/solution-workspace/` 的本机固定磁盘，不得放在 NFS、SMB、
  NAS、同步盘或源码目录。
- 当前版本只完成了 SQLite 的迁移、备份和恢复验证。不能只把 URL 改成 PostgreSQL/MySQL；
  跨数据库上线需要另做驱动、迁移、备份恢复和并发验收。
- 当前一键安装在 root 持有的发布目录中执行锁定的 `uv sync`；前端依赖安装和构建在独立暂存目录
  中由无密钥服务账号执行，固定使用 `npm ci --include=dev --prefer-offline`。只允许部署已评审、CI
  通过的提交和官方依赖源，不得在服务器直接构建未审查的 PR；后续正式发布流水线应改为独立构建
  账号生成制品，再由 root 原子安装制品。
- 这是内网 MVP 部署，不应直接暴露到互联网。公网、跨网或扩大用户规模前必须增加 HTTPS、
  反向代理、集中备份和重新安全评审。

## 2. 部署后的目录

| 路径 | 用途 | 权限/说明 |
|---|---|---|
| `/opt/solution-workspace/` | root 持有的源码、Python 虚拟环境和前端构建 | 运行账号只读 |
| `/etc/solution-workspace/app.env` | 运行配置和加密主密钥 | `0640 root:solution-workspace`，前端账号不可读 |
| `/etc/solution-workspace/deploy.conf` | 运维脚本使用的部署元数据 | `0640 root:solution-workspace` |
| `/var/lib/solution-workspace/` | SQLite 数据库和服务账号 HOME | 不由 Web 服务暴露 |
| `/var/lib/solution-workspace/releases/` | 人工转入的 bundle/离线发布文件 | `0700 root:root`，发布后清理 |
| `/var/backups/solution-workspace/` | 本机一致性备份和校验清单 | 仍需复制到异机 |
| `/var/cache/solution-workspace/npm/` | 无特权前端构建账号的 npm 内容缓存 | 不包含 `.npmrc` 或部署凭据 |
| `/usr/local/sbin/solution-workspace` | 统一运维命令 | root 执行 |

systemd 服务：

- `solution-workspace-backend.service`（账号 `solution-workspace`）
- `solution-workspace-frontend.service`（隔离账号 `solution-workspace-web`）
- `solution-workspace.target`
- `solution-workspace-backup.service`
- `solution-workspace-backup.timer`

## 3. 首次一键部署

### 3.1 准备代码

在服务器上检出明确的 `mvp` 分支并确认提交号：

```bash
git clone --branch mvp --single-branch https://github.com/OOOliver0428/lx_workbench.git
cd lx_workbench
git status --short --branch
git rev-parse HEAD
```

不要把本地 `.env`、测试数据库、备份或日志上传到仓库后再部署。

### 3.2 执行安装

把 `10.20.30.40` 换成用户实际访问的服务器 IP 或内网域名：

```bash
sudo bash deploy/ubuntu/install.sh --public-host 10.20.30.40
```

脚本会重复安全地执行以下工作：

1. 校验 Ubuntu、干净的 `mvp` 源码和项目结构；
2. 安装 Git、Node.js 22、`uv` 和构建依赖（已有合格版本时复用）；
3. 创建不可登录且彼此隔离的前端、后端服务账号；
4. 把指定提交复制为 `/opt/solution-workspace` 下 root 持有、运行账号只读的发布目录；
5. 首次部署时生成 `/etc/solution-workspace/app.env` 和稳定的 AI 配置加密主密钥；
6. 按锁文件安装 Python/Node 依赖并完成前端生产构建；
7. 安装、校验并启动 systemd 服务和每日备份定时器；
8. 执行 Alembic 数据库迁移以及前后端健康检查。

安装器不会覆盖已经存在的 `app.env`，因此不会意外更换数据库或加密主密钥。只要 `/opt` 发布目录
已经存在，默认就拒绝重复安装；日常升级请使用 `sudo solution-workspace update`。只有首次安装中断且
确认前端、后端、timer 和 backup service 全部停止时，才使用 `--repair-stopped-install` 修复。

如果服务器由运维提前准备了 Node.js、`uv` 和构建依赖，可以跳过系统包安装：

```bash
sudo bash deploy/ubuntu/install.sh \
  --public-host workspace.intra.example \
  --skip-system-packages
```

需要改端口时在首次部署传入参数：

```bash
sudo bash deploy/ubuntu/install.sh \
  --public-host 10.20.30.40 \
  --frontend-port 5174 \
  --backend-port 8787
```

### 3.3 创建首个管理员

```bash
sudo solution-workspace create-admin admin "系统管理员"
```

命令会在终端安全提示输入初始密码。不要把密码写进 Shell 历史、脚本或 Git。

### 3.4 首次验收

```bash
sudo solution-workspace status
sudo solution-workspace health
sudo solution-workspace backup
sudo solution-workspace logs backend 100
```

浏览器访问 `http://服务器IP:5174/`。确认登录、创建一条测试记录、刷新后仍存在，再检查审计日志。

## 4. 运行配置

活动配置文件为 `/etc/solution-workspace/app.env`。修改前先备份，修改后重启并检查：

```bash
sudo cp -a /etc/solution-workspace/app.env \
  /etc/solution-workspace/app.env.before-change
sudoedit /etc/solution-workspace/app.env
sudo solution-workspace restart
sudo solution-workspace health
```

关键配置：

| 配置 | 说明 |
|---|---|
| `MVP_ENVIRONMENT` | 服务器固定为 `production` |
| `MVP_DATABASE_URL` | 当前 SQLite URL，必须是 `/var/lib/solution-workspace/` 下的绝对路径 |
| `MVP_SERVER_HOST` | 固定 `127.0.0.1`，不要对内网直接开放后端 |
| `MVP_SERVER_PORT` | 应与部署时后端端口一致，默认 `8787` |
| `MVP_ALLOWED_HOSTS_CSV` | 浏览器实际使用的 IP/域名、`127.0.0.1`、`localhost` |
| `MVP_COOKIE_SECURE` | HTTP 试运行用 `false`；HTTPS 上线后必须为 `true` |
| `MVP_SESSION_TTL_HOURS` | 登录会话有效期，默认 12 小时 |
| `MVP_LLM_CONFIG_SECRET` | 数据库中 AI Provider 密钥的加密主密钥，必须长期保管且禁止随数据库切换而变化 |

如果切换域名或增加反向代理，要把最终请求的 `Host` 加入 `MVP_ALLOWED_HOSTS_CSV`。前端始终通过
同源 `/api` 转发，不需要开放后端端口或配置宽泛 CORS。

## 5. 试用库与正式库切换

### 5.1 默认试用库

首次部署默认创建：

```dotenv
MVP_DATABASE_URL=sqlite:////var/lib/solution-workspace/trial.db
```

查看当前库和 schema 版本：

```bash
sudo solution-workspace db-info
```

禁止在应用运行时手工覆盖 `.db`、`.db-wal` 或 `.db-shm` 文件。数据库切换统一使用
`solution-workspace switch-db` 或 `promote-db`。命令会获取全局互斥锁，停止应用和备份定时器，
生成无写入缺口的离线回滚快照，并只在候选副本上迁移 schema；候选库通过完整性、启动和健康检查
后才替换目标路径。失败时恢复原配置和原目标库。

切库维护窗口开始时，还必须在反向代理、网关或防火墙侧暂时阻断用户访问，直到命令成功、健康检查
通过并完成快速对账。仅依赖进程短暂停止不足以防止健康验证阶段出现新的业务写入。

### 5.2 试用数据不要带入正式环境

创建一个全新的正式库：

```bash
sudo solution-workspace switch-db /var/lib/solution-workspace/production.db
sudo solution-workspace create-admin admin "系统管理员"
```

新文件由 Alembic 创建为空库。管理员和正式业务基础数据需要重新建立。旧 `trial.db` 不会被删除，
应按批准的保留期归档，确认无用途后再由运维走删除审批。

### 5.3 保留全部试用数据并提升为正式库

使用专用提升命令，在维护窗口中冻结写入后克隆当前库：

```bash
sudo solution-workspace promote-db /var/lib/solution-workspace/production.db
```

该命令停服后才生成最终快照，因此不会遗漏“备份完成到停服之间”的写入。正式库由最终快照克隆，
原 `trial.db` 保持不变；命令输出还会给出独立的离线回滚快照路径。

切换后由业务负责人核对用户数、商机数、项目数、任务数、工作记录和最近周报，并保留原库及切换前
备份直到回滚窗口结束。严禁试用库和正式库同时开放写入。

### 5.4 使用外部提供的 SQLite 数据库

先把文件复制到数据目录，收紧权限，再独立校验和切换。目标库不会被原地迁移；脚本迁移候选副本，
并把原目标保存为带 `pre-switch` 后缀的文件：

```bash
sudo install -m 0600 -o solution-workspace -g solution-workspace \
  /approved-transfer/incoming.db \
  /var/lib/solution-workspace/imported.db
sudo solution-workspace verify-db /var/lib/solution-workspace/imported.db
sudo solution-workspace switch-db /var/lib/solution-workspace/imported.db
```

如果该库来自旧版本，`switch-db` 会执行当前 Alembic 迁移。切换前仍应在隔离服务器演练并做业务对账。

### 5.5 切回旧库

旧库文件仍保留时可执行同一命令回切：

```bash
sudo solution-workspace switch-db /var/lib/solution-workspace/trial.db
```

如果新版本已经执行不可逆 schema 迁移，不能盲目回滚旧代码；先确认目标提交与数据库 revision 兼容。

## 6. 日常运维命令

```bash
# 状态和健康
sudo solution-workspace status
sudo solution-workspace health

# 启停
sudo solution-workspace start
sudo solution-workspace stop
sudo solution-workspace restart

# 日志
sudo solution-workspace logs backend 200
sudo solution-workspace logs frontend 200
sudo solution-workspace logs backup 200

# 数据库
sudo solution-workspace db-info
sudo solution-workspace migrate
sudo solution-workspace verify-db /path/to/backup.db
sudo solution-workspace promote-db /var/lib/solution-workspace/production.db

# 手工备份
sudo solution-workspace backup
```

服务异常退出会由 systemd 自动重启。`status` 同时显示前端、后端、备份定时器和实时健康检查。

## 7. 备份、异机副本与恢复

### 7.1 自动备份

`solution-workspace-backup.timer` 每天约 02:15（Asia/Shanghai，带最多 30 分钟随机延迟）执行。
本机日备自动保留 30 天，清理只匹配备份根目录的 `mvp-*.db` 及配套 manifest；更新、迁移、
切库的专用回滚目录不会自动删除，应在回滚窗口关闭后按审批清理。
每次成功会产生：

- `mvp-时间戳.db`：SQLite 一致性快照；
- `mvp-时间戳.db.manifest.json`：SHA-256、大小、表数和 schema revision。

查看计划和最近结果：

```bash
sudo systemctl list-timers solution-workspace-backup.timer
sudo solution-workspace logs backup 100
```

本机 `/var/backups` 不是完整灾备。必须由公司备份平台或受控任务每天复制到异机位置，并监控：

- 最近 24 小时是否有成功备份；
- `.db` 和 manifest 是否同时存在；
- 异机副本 SHA-256 是否一致；
- 磁盘空间、保留期和复制失败告警。

建议保留策略为 7 个日备、4 个周备、6 个月备；最终以数据所有者批准的 RPO/RTO 为准。

### 7.2 从备份恢复

恢复采用“复制为新库再切换”，不会覆盖当前库。恢复会让备份时间点之后的数据暂时不出现在活动库，
必须由业务负责人确认 RPO，并决定是否需要人工重放这段记录：

```bash
sudo solution-workspace verify-db \
  /var/backups/solution-workspace/mvp-YYYYMMDDTHHMMSSZ.db
sudo install -m 0600 -o solution-workspace -g solution-workspace \
  /var/backups/solution-workspace/mvp-YYYYMMDDTHHMMSSZ.db \
  /var/lib/solution-workspace/recovered-YYYYMMDD.db
sudo solution-workspace switch-db \
  /var/lib/solution-workspace/recovered-YYYYMMDD.db
```

恢复后必须做业务对账，而不只是确认页面能打开：记录总数、关键商机/项目、用户、最近工作记录、
周报和审计事件均应抽样核对。

## 8. 版本更新与回滚

正常更新先在线获取版本；进入维护窗口并停止写入后再生成最终回滚快照，只接受 Git fast-forward，
然后按锁文件重新安装、构建、迁移和健康检查。候选前端会先在独立暂存目录中安装和构建；如果 npm
依赖或构建失败，当前线上版本保持运行，不会清空正在使用的 `node_modules`：

```bash
sudo solution-workspace update origin mvp
```

更新前确认：

- 仓库工作区干净；
- 目标提交已通过 CI；
- 当前备份成功且异机副本可用；
- Alembic 迁移和旧版本兼容性已评审；
- 已安排维护窗口。

### 8.1 GitHub 不可达时使用增量 bundle

`update` 的第一个参数既可以是远程名称，也可以是本地 Git bundle。先在服务器记录当前提交：

```bash
sudo git -C /opt/solution-workspace rev-parse HEAD
```

在能访问 GitHub 的受信任电脑上更新 `mvp`，用上一步提交号生成并校验增量包：

```bash
git fetch origin mvp
git switch mvp
git merge --ff-only origin/mvp
git bundle create solution-workspace-update.bundle 服务器当前提交号..mvp
git bundle verify solution-workspace-update.bundle
sha256sum solution-workspace-update.bundle
```

将 bundle 通过 SCP、堡垒机或批准的介质先传到服务器临时目录，通过独立可信通道核对 SHA-256
和目标提交号，再转存为 root 持有的发布文件并验证 bundle：

```bash
sudo install -d -m 0700 -o root -g root /var/lib/solution-workspace/releases
sudo install -m 0600 -o root -g root \
  /tmp/solution-workspace-update.bundle \
  /var/lib/solution-workspace/releases/solution-workspace-update.bundle
sudo git -C /opt/solution-workspace bundle verify \
  /var/lib/solution-workspace/releases/solution-workspace-update.bundle
sudo solution-workspace update \
  /var/lib/solution-workspace/releases/solution-workspace-update.bundle mvp
sudo solution-workspace health
```

bundle 只替代 GitHub 代码传输，不自动携带 npm/Python 依赖。更新器会优先复用本机缓存，但缓存缺失
时仍需访问配置的软件源。完全断网环境必须另外制作并校验依赖缓存/制品，不能把 Git bundle 当作
完整离线安装包。首次升级到无特权构建流程时，更新器会把旧 root npm 内容缓存迁移到前端构建
账号的专用缓存目录，但不会复制 `.npmrc` 或凭据。前端候选构建失败时，脚本会在停服前退出并
保留当前版本；不要反复执行更新。

如果服务器当前版本不晚于 `4fe59b1`，旧更新器既可能漏装 `devDependencies`，也会用仅 root 可读
的 umask 构建前端。不能直接调用旧版 `update`。先从已经校验的 bundle 中只取出新版运维脚本，
校验 Bash 语法并备份旧脚本：

```bash
sudo bash -c '
  set -Eeuo pipefail
  umask 0022
  bundle=/var/lib/solution-workspace/releases/solution-workspace-update.bundle
  project=/opt/solution-workspace
  candidate=/usr/local/sbin/solution-workspace.next
  git -C "$project" bundle verify "$bundle"
  git -C "$project" fetch "$bundle" mvp
  git -C "$project" show FETCH_HEAD:deploy/ubuntu/ops.sh >"$candidate"
  test -s "$candidate"
  bash -n "$candidate"
  cp -a /usr/local/sbin/solution-workspace \
    /usr/local/sbin/solution-workspace.before-staged-update
  install -m 0755 -o root -g root "$candidate" /usr/local/sbin/solution-workspace
  /usr/local/sbin/solution-workspace update "$bundle" mvp
  /usr/local/sbin/solution-workspace health
'
```

更新成功后，新版 systemd 安装过程会再次安装同一份运维脚本。确认健康检查和备份 timer 正常后，
删除 `.next`、旧脚本备份和发布 bundle。候选 npm 生命周期与前端构建由无密钥的前端服务账号执行，
不会以 root 身份读取 `app.env` 或部署凭据。

### 8.2 更新失败与版本感知回滚

如果更新在构建或迁移阶段失败，脚本会保持应用和备份定时器停止，输出旧/新提交以及准确的离线
回滚快照。不要在新代码下对该快照执行 `switch-db`，否则它会再次迁移到新 schema。版本感知回滚：

1. 保持服务停止，保存失败日志和 `/var/backups/solution-workspace/updates/.../update.env`；
2. 使用当前运维命令 `verify-db` 校验输出的升级前快照；
3. 把快照复制成 `/var/lib/solution-workspace/rollback-日期.db` 并设置 `0600 solution-workspace`；
4. 直接编辑 `/etc/solution-workspace/app.env`，把 `MVP_DATABASE_URL` 指向该回滚库；此时不要启动；
5. 检查 `update.env` 中的 `FRONTEND_RUNTIME_SWAPPED`：`false` 表示交换尚未开始；`true` 表示交换
   完整结束；`in_progress` 表示交换被中断，必须保持停服并检查 live/previous 两组目录，不得自动
   选择任一组。只有值为 `true`，且 `FRONTEND_RUNTIME_BACKUP` 下同时存在 `node_modules` 和 `dist`
   时，才执行下列恢复块。不要以 root 运行 npm 生命周期脚本：

   ```bash
   sudo git -C /opt/solution-workspace switch --detach 旧提交
   sudo env \
     UV_PYTHON_INSTALL_DIR=/opt/solution-workspace-runtime/python \
     UV_CACHE_DIR=/var/cache/solution-workspace/uv \
     uv sync --project /opt/solution-workspace --frozen --no-dev --python 3.12
   sudo bash -c '
     set -Eeuo pipefail
     metadata=/var/backups/solution-workspace/updates/具体时间/update.env
     swapped=$(sed -n "s/^FRONTEND_RUNTIME_SWAPPED=\\(false\\|in_progress\\|true\\)$/\\1/p" "$metadata")
     backup=$(sed -n "s#^FRONTEND_RUNTIME_BACKUP=\\(/opt/solution-workspace\\.frontend-update\\.[A-Za-z0-9]*/previous\\)$#\\1#p" "$metadata")
     test "$swapped" = true
     test -n "$backup"
     live=/opt/solution-workspace/frontend
     test "$(realpath -- "$backup")" = "$backup"
     test -d "$backup/node_modules"
     test -d "$backup/dist"
     mv "$live/node_modules" "$live/node_modules.failed"
     mv "$live/dist" "$live/dist.failed"
     mv "$backup/node_modules" "$live/node_modules"
     mv "$backup/dist" "$live/dist"
     chown -R root:root "$live/node_modules" "$live/dist"
     chmod -R u=rwX,go=rX "$live/node_modules" "$live/dist"
   '
   ```

   如果状态为 `in_progress`、运行时备份不完整或路径校验失败，保持停服并人工核对；不得继续执行
   `mv`。如果运行时备份不存在，必须取得对应旧提交的已审核制品或由无特权构建账号重新生成；
   不要临时改成 root 执行 `npm ci`。

6. 确认旧提交的 Alembic `head` 与回滚快照 revision 一致，然后启动现有 systemd target；
7. 完成健康检查和业务对账后恢复备份 timer。若任一步无法确认，保持停服并联系发布负责人取得
   对应旧版本制品，不允许盲目降级 schema。

私有仓库执行 `update` 前，应为 root 配置只读 deploy key 或公司批准的凭据；不要把访问令牌写入远端 URL。

## 9. 网络与 HTTPS

HTTP 试运行只允许在受控内网：

```bash
# 示例：仅允许 10.20.30.0/24 访问前端
sudo ufw allow from 10.20.30.0/24 to any port 5174 proto tcp
sudo ufw deny 8787/tcp
```

不要照抄示例网段；应使用公司批准的实际网段。启用 Nginx/Caddy/公司网关 HTTPS 后：

1. 只让反向代理访问前端端口；
2. 在 `MVP_ALLOWED_HOSTS_CSV` 中加入正式域名；
3. 设置 `MVP_COOKIE_SECURE=true`；
4. 重启并重新验证登录、Session、CSRF 和同源 `/api`。

## 10. 故障排查

### `runuser: command not found`

新版本已经把 `/usr/sbin` 加入运维脚本的固定系统路径，并在安装时校验 `util-linux` 提供的
`runuser`。旧安装可以先修复已安装的脚本，再执行更新：

```bash
sudo sed -i 's#/usr/local/bin:/usr/bin:/bin#/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin#' /usr/local/sbin/solution-workspace
sudo apt-get install -y util-linux
sudo solution-workspace update
```

### 页面打不开

```bash
sudo solution-workspace status
sudo solution-workspace health
sudo solution-workspace logs frontend 200
```

确认 `5174` 正在监听、UFW/安全组允许正确网段，且访问 Host 已加入允许列表。

### 页面能打开但 API 失败

```bash
sudo solution-workspace logs backend 200
curl -fsS http://127.0.0.1:8787/api/v1/health/ready
```

检查后端服务、数据库权限、磁盘空间和 Alembic revision。不要把 `8787` 开放给终端绕过前端代理。

### 数据库只读、锁定或磁盘不足

立即停止写入并保存日志：

```bash
sudo solution-workspace stop
df -h /var/lib/solution-workspace /var/backups/solution-workspace
sudo solution-workspace logs backend 300
```

不得在服务运行时删除 WAL/SHM 文件。空间和权限恢复后先校验备份，再启动并做业务抽样。

### 自动备份失败

```bash
sudo systemctl start solution-workspace-backup.service
sudo solution-workspace logs backup 200
```

检查备份目录可写性、空间以及当前数据库 URL。备份超过已批准 RPO 时应停止继续扩大业务写入并升级告警。

## 11. 上线/切库检查清单

- [ ] 目标提交号已记录，CI 和目标 Ubuntu 验证均通过。
- [ ] 服务器仅对批准网段开放前端入口，后端未对外开放。
- [ ] `app.env` 权限为 `0640 root:solution-workspace`，前端账号不可读，且未进入 Git/Web 根目录。
- [ ] `/opt/solution-workspace` 为 root 持有并去除 group/other 写权限，运行账号只有读取权。
- [ ] `MVP_LLM_CONFIG_SECRET` 已存入密码管理器并有受控备份。
- [ ] 当前数据库位于本机 `/var/lib/solution-workspace/`，不是网络或同步磁盘。
- [ ] 自动备份成功，异机复制和告警已配置。
- [ ] 至少完成一次从备份复制为新库、切换、健康检查和业务对账演练。
- [ ] 创建了独立管理员账号，默认/试用密码已更换。
- [ ] 试用转正式的“丢弃数据”或“保留数据”方案已由业务负责人确认。
- [ ] 切库前后记录数、关键样本、周报和审计事件完成对账。
- [ ] 回滚窗口、责任人、RPO/RTO 和备份保留期已确认。
