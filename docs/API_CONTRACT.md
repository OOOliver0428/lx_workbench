# MVP 前后端契约

后端 OpenAPI 是接口契约的唯一事实来源：

```text
http://127.0.0.1:8787/openapi.json
http://127.0.0.1:8787/docs
```

前端在 `frontend/app/types.ts` 中维护与 OpenAPI 对齐的 TypeScript 类型，在
`frontend/app/api.ts` 中集中处理 Cookie Session、CSRF 和错误响应。业务组件不得自行拼接
API 地址或直接读取 CSRF。

## 命名

- HTTP JSON 字段统一使用 `snake_case`。
- 日期时间使用 ISO 8601 字符串，日期使用 `YYYY-MM-DD`。
- 数据实体 ID 使用字符串 UUID。
- 所有可并发修改的实体携带整数 `revision`；写操作提交当前 `revision`。

## 认证

- `POST /api/v1/auth/login` 的 `login_name` 字段接受登录名或显示名称；两者比较时均去除
  首尾空格并忽略大小写。字段名为兼容现有客户端而保留。
- `POST /api/v1/auth/login` 和 `GET /api/v1/auth/me` 均返回：

```json
{
  "user": {},
  "csrf_token": "...",
  "expires_at": "...",
  "permissions": ["dashboard.opportunity.view", "work_records.view"]
}
```

- Session 只保存在 HttpOnly Cookie 中。
- Session 默认有效期为12小时，可通过 `MVP_SESSION_TTL_HOURS` 调整；前端按
  `expires_at` 主动返回登录页，任意业务接口返回401时也会立即清理本地会话。
- 除 `GET`、`HEAD`、`OPTIONS` 外的业务请求通过 `X-CSRF-Token` 发送 CSRF 值。
- 首次登录且 `must_change_password=true` 时，只允许读取当前会话、修改密码或退出。
- 管理员设置的初始密码至少10位；首次登录设置的新密码只要求至少5位。

## 权限与可见性

- 权限按用户显式保存。除超级管理员外，角色不自动附带业务权限；新账号默认权限集合为空。
- 超级管理员的有效权限始终是权限目录全集，不依赖数据库授权记录。
- 超级管理员对其他所有用户永久不可见：不出现在 `GET /api/v1/users`、直属负责人候选、
  项目成员、任务协作者、周报收件范围和权限配置目标中。即使调用者也是超级管理员，
  用户目录仍不返回超级管理员账号。
- 超级管理员可读取 `GET /api/v1/users/permissions/catalog`，并通过
  `GET/PUT /api/v1/users/{user_id}/permissions` 配置任一非超级管理员账号。
- 系统管理员具备下级权限配置入口，但只能读取和修改 `member`、`team_leader` 的业务权限；
  `settings.users.manage`、`settings.tags.manage`、`settings.ai.manage`、
  `settings.audit.view` 等系统级权限只能由超级管理员授予。系统管理员不能把角色提升为
  系统管理员，也不能配置系统管理员或超级管理员。
- 权限更新是全量替换，并携带目标用户当前 `revision` 做乐观锁校验；变更写入审计日志。
- 管理权限会隐含对应查看权限，例如 `projects.manage` 隐含 `projects.view`；
  `dashboard.team_summary.generate` 隐含 `dashboard.work.view`。接口返回
  `assigned_permissions` 与展开后的 `effective_permissions`，避免前端自行推导。

## 账号与个人设置

- `POST /api/v1/users`、用户资料和直属负责人写接口要求 `settings.users.manage`。超级管理员
  始终具备该权限；系统管理员只有在超级管理员显式授予后才能使用，且只能管理团队负责人和
  团队成员。请求只接受 `display_name`、`role` 和 `password`，登录名由后端生成，直属
  Leader 在创建后另行配置。
- 显示名称在全系统内唯一（去除首尾空格并忽略大小写），且不能与其他账号的登录名冲突。
  创建或编辑用户发生冲突时返回 `409 DISPLAY_NAME_ALREADY_EXISTS`。唯一性检查包含对普通
  用户不可见的超级管理员账号，但错误响应不会暴露冲突账号的信息。
- 所有已完成首次密码修改的用户都可读取 `GET /api/v1/profile/avatars` 并调用
  `PATCH /api/v1/profile/avatar` 修改自己的头像。
- 头像接口只接受服务端白名单中的固定 `avatar_key` 或 `null`，不接受上传、文件路径或外部 URL；
  修改必须携带本人当前 `revision` 并进入审计日志。
- 所有用户都可调用 `POST /api/v1/auth/change-password` 修改自己的密码；修改成功后除当前会话外，
  本人的其他登录会话全部失效。

## 错误

所有 API 错误统一返回：

```json
{
  "code": "STABLE_MACHINE_CODE",
  "message": "可直接展示给用户的信息",
  "request_id": "用于日志定位的请求 ID",
  "details": null
}
```

前端以 `code` 决定业务分支，以 `message` 展示提示；`request_id` 用于问题排查，不作为业务值。

## 工作记录权限

- 调用工作记录接口首先需要 `work_records.view` 或 `work_records.manage`；拥有菜单可见性
  并不会绕过后端权限校验。
- 团队成员、团队负责人和系统管理员仍只能查看、修改或删除自己的原始工作记录。
- 只有永久隐藏的超级管理员可以跨用户查看工作记录；代编辑和代删除仍必须填写原因并进入审计日志。
- 非超级管理员不可通过工作记录审计事件读取他人的正文快照。
- 作战台中的工作条目、工时与由工作记录产生的交付物遵循同一边界：非超级管理员只聚合
  本人的记录，超级管理员可聚合全部记录。项目公开进展事实不受此限制。
- 工作记录响应同时返回 `author_id`、`author_display_name`、`author_avatar_key`、
  `last_edited_by`、`last_editor_display_name` 和 `last_editor_avatar_key`。超级管理员查看
  多人记录时，前端必须显示记录人与其头像；发生代编辑时还必须显示最后代编辑人。

## 作战台聚合

- `GET /api/v1/dashboard?week_start=YYYY-MM-DD` 返回所选自然周及最近五周的商机、任务、工作记录摘要、交付物、成员周报提交状态、阶段分布和趋势；`week_start` 会归一化到周一。
- 作战台不接受浏览器提交统计结果。项目、任务、工作记录、交付物和已提交周报仍是唯一业务事实，服务端负责聚合并执行数据范围校验。
- `dashboard.opportunity.view`、`dashboard.work.view` 和 `dashboard.overview.view` 分别控制
  “商机追踪”“工作管理”“周期总览”。除超级管理员外不按角色预设可见页签；没有任何作战台
  视图权限时，聚合接口返回 403。
- 原始工作记录始终只对本人和超级管理员可见。个人周报是否提交、直属负责人关系和作战台
  视图权限都不会扩大原始记录、正文或工时的可见范围。
- `POST /api/v1/projects/{project_id}/progress` 追加一条指定周的项目阶段、关注状态、进度和摘要事实，不覆盖历史。仅项目负责人和管理角色可写入。
- `POST /api/v1/tasks/relations` 建立不同项目任务之间的关联。调用者必须同时具备两个项目的管理权限，同一任务对不可重复关联。
- `POST /api/v1/dashboard/team-summary?week_start=YYYY-MM-DD` 只读取该周已正式提交、且当前负责人有权读取的个人周报。默认要求范围内全员提交；`force=true` 可在缺交时继续生成，并永久记录实际人数、预期人数和强制标记。该接口要求 `dashboard.team_summary.generate`；历史汇总按生成负责人隔离，成员或其他负责人不能通过作战台读取其正文。
- `GET /api/v1/weekly-reports/team-summaries` 同样要求
  `dashboard.team_summary.generate`，且只返回当前用户自己生成的历史团队周报。

## AI 边界

- 浏览器通过 `/api/v1/ai/providers` 和 `/api/v1/ai/configuration` 读取服务商预设与脱敏配置摘要。
- `/api/v1/ai/configuration/test` 和配置写接口要求 `settings.ai.manage`；超级管理员始终具备，
  其他账号必须由超级管理员显式授权。
- 只有携带有效验证令牌的 `PUT /api/v1/ai/configuration` 才能保存配置；更换服务商、接入方式、模型或 API Key 后必须重新测试。
- MiniMax `token_plan` 使用 Anthropic 兼容协议和 `sk-cp-` Key；`pay_as_you_go` 使用 OpenAI 兼容协议和普通 API Key，两类密钥在发起外部请求前强制校验、不可混用。
- API Key 由后端加密后存入数据库，响应只返回末尾提示，不会进入前端持久化存储、日志或审计详情。
- 浏览器通过 `/api/v1/ai/status` 和 `/api/v1/ai/chat` 使用当前生效配置；数据库配置优先于兼容期环境变量。
- AI 请求需要有效 Session；聊天写操作还需要 CSRF。
- AI 输出是辅助建议，不直接写入项目、任务或工作记录。

## 直属 Leader

- `users.leader_id` 是独立的组织属性，不等同于项目负责人或系统角色。
- 直属 Leader 候选人必须是有效的 `team_leader` 或 `system_admin` 账号，禁止自指派和形成管理环；隐藏超级管理员不作为候选人。
- 具备 `settings.users.manage` 的账号可调用 `PATCH /api/v1/users/{user_id}/leader` 修改权限
  范围内用户的直属 Leader；修改必须携带用户当前 `revision` 并写入审计日志。
- 具备 `settings.users.manage` 的账号可通过 `PATCH /api/v1/users/{user_id}` 修改权限范围内用户
  的显示名称、角色和直属 Leader。只有超级管理员能创建系统管理员或将角色提升、降级为
  系统管理员；仍有直属成员的团队负责人必须先转移成员，之后才能降级。
- 隐藏超级管理员不出现在用户目录中，也不能通过该接口成为操作目标。

## AI 上下文与周报

- `POST /api/v1/ai/chat` 的业务上下文由后端根据当前用户生成，浏览器不能提交或扩大上下文范围。普通问答只包含与当前用户有关的项目、任务及其最近工作记录，结果仅供阅览。
- 周报自然周固定为周一至周日，时区按 `Asia/Shanghai` 计算。
- `POST /api/v1/weekly-reports/current/generate` 只读取当前用户本周的工作记录；项目只有在本周至少存在一条该用户工作记录时才会进入模型上下文。未关联项目的工作记录会单独提供给模型。
- 每个用户每个自然周只有一条周报记录，以 `(author_id, week_start)` 唯一约束保证。AI 生成结果立即保存为草稿。
- `GET /api/v1/weekly-reports` 只返回当前用户自己的周报，并按周目倒序排列；不存在负责人
  收件箱或超级管理员跨用户读取个人周报的接口。
- 草稿内容与已提交内容分开保存。保存或重新生成草稿不会改变团队周报生成时可汇总的正式版本。
- `POST /api/v1/weekly-reports/{id}/submit` 将正式版本标记到用户当前有效的直属团队范围，
  供具有团队周报生成权限的用户在后端汇总，但不提供个人周报收件箱。若本周已有已提交
  版本，必须显式传入 `overwrite_confirmed=true`，否则返回
  `WEEKLY_REPORT_OVERWRITE_CONFIRMATION_REQUIRED`。
- 提交状态仅用于后端生成团队周报时判断可汇总版本，不赋予直属负责人、系统管理员或
  超级管理员直接查看该个人周报的能力。所有角色都只能通过个人周报接口读取自己的内容。
