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

- `POST /api/v1/auth/login` 和 `GET /api/v1/auth/me` 均返回：

```json
{
  "user": {},
  "csrf_token": "...",
  "expires_at": "..."
}
```

- Session 只保存在 HttpOnly Cookie 中。
- Session 默认有效期为12小时，可通过 `MVP_SESSION_TTL_HOURS` 调整；前端按
  `expires_at` 主动返回登录页，任意业务接口返回401时也会立即清理本地会话。
- 除 `GET`、`HEAD`、`OPTIONS` 外的业务请求通过 `X-CSRF-Token` 发送 CSRF 值。
- 首次登录且 `must_change_password=true` 时，只允许读取当前会话、修改密码或退出。
- 管理员设置的初始密码至少10位；首次登录设置的新密码只要求至少5位。

## 账号与个人设置

- 只有系统管理员和超级管理员可调用 `POST /api/v1/users` 创建业务账号；请求只接受
  `display_name`、`role` 和 `password`，登录名由后端生成，直属 Leader 在创建后另行配置。
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

- 普通成员、团队负责人和系统管理员只能查看、修改或删除自己的原始工作记录。
- 只有隐藏超级管理员可以跨用户查看工作记录；代编辑和代删除仍必须填写原因并进入审计日志。
- 非超级管理员不可通过工作记录审计事件读取他人的正文快照。
- 工作记录响应同时返回 `author_id`、`author_display_name`、`author_avatar_key`、`last_edited_by`、`last_editor_display_name` 和 `last_editor_avatar_key`。多人记录可能同时出现时，前端必须显示记录人与其头像；发生代编辑时还必须显示最后代编辑人。

## AI 边界

- 浏览器通过 `/api/v1/ai/providers` 和 `/api/v1/ai/configuration` 读取服务商预设与脱敏配置摘要。
- 系统管理员与超级管理员可调用 `/api/v1/ai/configuration/test`；测试会消耗少量 Token，并返回短时、一次配置绑定的验证令牌。
- 只有携带有效验证令牌的 `PUT /api/v1/ai/configuration` 才能保存配置；更换服务商、接入方式、模型或 API Key 后必须重新测试。
- MiniMax `token_plan` 使用 Anthropic 兼容协议和 `sk-cp-` Key；`pay_as_you_go` 使用 OpenAI 兼容协议和普通 API Key，两类密钥在发起外部请求前强制校验、不可混用。
- API Key 由后端加密后存入数据库，响应只返回末尾提示，不会进入前端持久化存储、日志或审计详情。
- 浏览器通过 `/api/v1/ai/status` 和 `/api/v1/ai/chat` 使用当前生效配置；数据库配置优先于兼容期环境变量。
- AI 请求需要有效 Session；聊天写操作还需要 CSRF。
- AI 输出是辅助建议，不直接写入项目、任务或工作记录。

## 直属 Leader

- `users.leader_id` 是独立的组织属性，不等同于项目负责人或系统角色。
- 直属 Leader 候选人必须是有效的 `team_leader` 或 `system_admin` 账号，禁止自指派和形成管理环；隐藏超级管理员不作为候选人。
- 系统管理员和超级管理员可调用 `PATCH /api/v1/users/{user_id}/leader` 修改其他用户的直属 Leader；修改必须携带用户当前 `revision` 并写入审计日志。
- 系统管理员和超级管理员可通过 `PATCH /api/v1/users/{user_id}` 修改已有用户的显示名称、角色和直属 Leader。管理员不能修改自己的角色；仍有直属成员的团队负责人必须先转移成员，之后才能降级。
- 隐藏超级管理员不出现在用户目录中，也不能通过该接口成为操作目标。

## AI 上下文与周报

- `POST /api/v1/ai/chat` 的业务上下文由后端根据当前用户生成，浏览器不能提交或扩大上下文范围。普通问答只包含与当前用户有关的项目、任务及其最近工作记录，结果仅供阅览。
- 周报自然周固定为周一至周日，时区按 `Asia/Shanghai` 计算。
- `POST /api/v1/weekly-reports/current/generate` 只读取当前用户本周的工作记录；项目只有在本周至少存在一条该用户工作记录时才会进入模型上下文。未关联项目的工作记录会单独提供给模型。
- 每个用户每个自然周只有一条周报记录，以 `(author_id, week_start)` 唯一约束保证。AI 生成结果立即保存为草稿。
- 草稿内容与已提交内容分开保存。保存或重新生成草稿不会改变 Leader 已看到的版本。
- `POST /api/v1/weekly-reports/{id}/submit` 提交给用户当前有效的直属 Leader。若本周已有已提交版本，必须显式传入 `overwrite_confirmed=true`，否则返回 `WEEKLY_REPORT_OVERWRITE_CONFIRMATION_REQUIRED`。
- 团队负责人和系统管理员只能读取提交给自己的周报；超级管理员可以读取全部已提交周报。所有角色均不能通过周报接口读取他人草稿。
