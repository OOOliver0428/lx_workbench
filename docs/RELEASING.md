# 版本发布与更新日志规范

当前代码版本：**0.4.1**。热修复验证后同步 `dev` 与 `main`；创建 `v0.4.1` 标签和 GitHub Release
属于正式发布步骤。

本文规定从 `0.1.0` 开始的版本号、更新日志、Git 标签和发布检查流程。目标是让每次迭代都能回答：
改了什么、是否需要迁移或改配置、如何部署、是否可以回滚。

## 1. 版本号

项目采用语义化版本 `MAJOR.MINOR.PATCH`：

- `PATCH`：向后兼容的缺陷修复、文案或运维改进，例如 `0.1.0 → 0.1.1`；
- `MINOR`：向后兼容的新功能或明显能力扩展，例如 `0.1.1 → 0.2.0`；
- `MAJOR`：不兼容的 API、数据或部署变更。进入稳定发布后使用 `1.x → 2.0.0`。

在 `0.x` 阶段，破坏性变更可以提升 `MINOR`，但必须在更新日志中标为 **Breaking**，并给出迁移和
回滚限制。不要只按提交数量或日期提升版本。

版本号必须在以下位置保持一致：

1. 根目录 `pyproject.toml` 的 `[project].version`；
2. `uv.lock` 中根项目条目（`name = "team-project-mvp"`）的 `version`；
3. `app/__init__.py` 的 `__version__`；
4. `app/main.py` 的 FastAPI `version`；
5. `frontend/package.json` 的 `version`；
6. `frontend/package-lock.json` 顶层和根 package 的 `version`；
7. `CHANGELOG.md` 对应版本标题；
8. Git 标签 `vMAJOR.MINOR.PATCH`。

## 2. 每次迭代如何维护更新日志

开发期间，把尚未发布但影响用户或运维的内容写入 `CHANGELOG.md` 的 `Unreleased`。使用以下分类：

- `Added`：新增功能、接口、命令或文档能力；
- `Changed`：行为、默认值、权限、交互或兼容性变化；
- `Fixed`：用户可见缺陷和部署故障修复；
- `Security`：鉴权、密钥、数据隔离和安全加固；
- `Operations`：部署、升级、备份、监控、数据库和回滚变化；
- `Deprecated` / `Removed`：弃用或删除，仅在实际需要时增加。

记录结果和影响，不抄提交标题。以下变更必须写更新日志：

- 用户能看到或依赖的功能、权限、默认行为和界面变化；
- API、环境变量、端口、依赖最低版本或 systemd 单元变化；
- Alembic 迁移、数据修复、备份格式、切库或回滚兼容性变化；
- 安全修复和重要性能变化；
- 已部署环境需要执行的人工步骤。

纯重构、测试内部整理和不影响交付的注释可以不记录，但合并请求中要说明“不需要更新日志”的原因。

## 3. 分支策略

- `main`：发布主线。服务器只部署带版本标签的 `main` 提交；合并进入 `main` 的内容必须已通过 CI
  并完成版本与更新日志归档。
- `dev`：日常开发分支。功能分支从 `dev` 切出，完成后合并回 `dev`。
- `prototype`：0.2 之前的旧原型主线，只读保留，禁止提交与合并。
- `mvp`：已停止使用，仅保留历史，不再作为发布或部署分支。

## 4. 发布步骤

1. 确认 `main`（或待合并的 `dev`）工作区干净，目标提交通过全部 CI。
2. 根据变更兼容性确定新版本号。
3. 同步修改 `pyproject.toml`、`uv.lock` 根项目条目、`app/__init__.py`、`app/main.py`、
   `frontend/package.json` 和 `frontend/package-lock.json`。
4. 把 `CHANGELOG.md` 中的 `Unreleased` 内容归档为 `## [X.Y.Z] - YYYY-MM-DD`，再建立空的
   `Unreleased` 分类。
5. 在更新日志的 `Operations` 中写明：
   - 是否存在 Alembic 迁移；
   - 是否新增或修改环境变量；
   - 是否需要停机维护；
   - 数据库和旧代码是否可以直接回滚；
   - bundle 更新是否需要额外依赖缓存或制品。
6. 执行发布检查：

   ```bash
   uv run ruff check app tests
   uv run pytest
   npm --prefix frontend run lint
   npm --prefix frontend test
   bash deploy/systemd/verify-templates.sh
   bash -n deploy/ubuntu/install.sh
   bash -n deploy/ubuntu/ops.sh
   ```

7. 将 `dev` 合并到 `main`（fast-forward 或合并提交）并确认 GitHub Actions 通过后创建带说明的标签：

   ```bash
   git tag -a vX.Y.Z -m "Solution Workspace vX.Y.Z"
   git push origin vX.Y.Z
   ```

8. 使用该版本的更新日志创建 GitHub Release；发布说明必须包含升级步骤、数据库影响、已知限制和
   回滚条件。
9. 在服务器维护窗口执行更新，记录旧/新提交、回滚快照、健康检查和备份 timer 状态。

## 5. 发布后的服务器记录

每次部署至少保存以下结果到批准的运维记录中：

```bash
sudo git -C /opt/solution-workspace describe --tags --always
sudo git -C /opt/solution-workspace rev-parse HEAD
sudo solution-workspace db-info
sudo solution-workspace health
sudo systemctl is-enabled solution-workspace-backup.timer
sudo systemctl is-active solution-workspace-backup.timer
sudo systemctl list-timers solution-workspace-backup.timer
```

页面可打开不等于发布完成。还要抽样验证登录、关键查询、一次可回滚的测试写入、AI（如启用）、
备份生成及异机复制。

## 6. 热修复

生产或试运行阻断缺陷使用 `PATCH` 版本。即使只改一行，也不能绕过更新日志、CI、备份和标签。
紧急修复若暂时无法完成非关键文档，可在 `Unreleased` 中明确欠项，并在同一补丁周期补齐；数据库
回滚说明和安全影响不可延期。
