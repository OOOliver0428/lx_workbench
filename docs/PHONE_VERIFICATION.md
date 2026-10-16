# 可选手机号认证（计划随 v0.5.1 发布）

手机号功能默认关闭；个人设置自愿补绑，不改变密码登录或业务权限。首期仅支持 +86，
一号一账号（冻结仍占用），换绑需当前密码和新号码短信。仅本人看到脱敏号码与认证时间。
本期没有管理员代认证、解绑、短信登录或外部身份关联。

## 升级与启用

1. 停止应用并备份数据库，保留原环境文件；同步 Python 锁定依赖后执行
   `python -m app.cli upgrade-db`。新迁移 `a9b8c7d6e5f4` 的父版本为 `f8a1b2c3d4e5`。
2. 在 `.env`（开发）或 `/etc/solution-workspace/app.env`（部署）加入下列配置。
   生产文件沿用 `0640 root:solution-workspace`，不要提交到仓库，也不要把整个环境文件传给前端。
3. 先保持功能关闭，配置专用于手机号模块的密钥和阿里云参数，再设为 true 并重启后端。
   公开图形参数通过已登录接口提供，修改参数不需要重新构建前端。
4. 从个人设置做一次真实图形验证、短信绑定和换绑；检查 CSP、错误提示及脱敏审计。
   CI 使用模拟服务商，不会消耗真实短信额度。

```dotenv
MVP_PHONE_VERIFICATION_ENABLED=false
# 示例只有占位符，不能直接使用。JSON 在 systemd EnvironmentFile 中用单引号包裹。
MVP_PHONE_ENCRYPTION_KEYS='{"v1":"<独立随机Fernet密钥>"}'
MVP_PHONE_ENCRYPTION_ACTIVE_KEY_ID=v1
MVP_PHONE_LOOKUP_KEY=<另一条独立随机32字节的URL-safe Base64密钥>
MVP_ALIYUN_ACCESS_KEY_ID=
MVP_ALIYUN_ACCESS_KEY_SECRET=
MVP_ALIYUN_CAPTCHA_PREFIX=
MVP_ALIYUN_CAPTCHA_SCENE_ID=
MVP_ALIYUN_SMS_SIGN_NAME=
MVP_ALIYUN_SMS_TEMPLATE_CODE=
MVP_ALIYUN_SMS_SCHEME_NAME=
MVP_PHONE_USER_HOUR_LIMIT=5
MVP_PHONE_USER_DAY_LIMIT=10
MVP_PHONE_NUMBER_HOUR_LIMIT=5
MVP_PHONE_NUMBER_DAY_LIMIT=10
MVP_PHONE_GLOBAL_HOUR_LIMIT=100
MVP_PHONE_GLOBAL_DAY_LIMIT=500
```

使用密码管理器或本地受控环境中的 `Fernet.generate_key()` 分别生成两个独立随机密钥，
直接保存进受保护的环境配置；不要使用易记口令，不要复用 AI 加密密钥、阿里云 AccessKey 或两类手机号密钥。
密钥应只在操作者受控环境处理，不放入命令行参数、聊天记录或日志。

阿里云需开通验证码 2.0，中国内地 Web/H5 场景建议使用滑块弹窗；配置 prefix 和 SceneId。
MVP_ALIYUN_CAPTCHA_PREFIX 取自验证码 2.0 控制台的「概览 → 身份标」，
MVP_ALIYUN_CAPTCHA_SCENE_ID 取自「场景管理 → 场景 ID」，接入方式选择 Web/H5。
号码认证服务「图形认证方案管理」中的 appId/appKey 是另一套接入参数，不能填写到这里；
当前代码未接入那套图形认证 SDK/校验接口。
服务端固定中国区验证码端点及 `dypnsapi.aliyuncs.com`，凭证使用具备相应最小调用权限的 RAM 用户。
短信方案名限 20 字符，使用本功能专用方案，避免与其他系统共用验证码空间。
签名和模板应符合已开通的短信认证服务规则，模板参数使用 code/min（验证码/分钟）。
后端固定 `{"code":"##code##","min":"5"}`，阿里云生成 6 位数字验证码；不返回验证码。

浏览器需要能访问阿里云 CDN、验证码和设备验证接口；后端需要能访问两个服务端 API。
这不要求将工作台开放到公网。前端 CSP 已按中国区接入开放必要来源。
参考：[Web V3 接入](https://help.aliyun.com/zh/captcha/captcha2-0/user-guide/new-architecture-for-web-and-h5-client-access)、
[网络域名说明](https://help.aliyun.com/zh/captcha/captcha2-0/user-guide/captcha-2-0-client-access-faq)。

## 存储和密钥连续性

用户和认证记录均在写 SQL 前加密。Fernet 随机认证加密负责保存号码，独立 HMAC-SHA256
指纹负责查询、唯一约束和号码频控；不保存明文、尾号或脱敏副本。密文内包含记录归属，
读取时核对归属及查询指纹。普通用户查询和登录不解密手机号。

数据库仅保存密钥 ID 及固定用途的密钥校验值，不保存任何密钥。
首次登记仅允许没有既有号码/认证数据的状态；误换查询密钥、重用密钥 ID 指向其他密钥、
缺少仍被使用的历史密钥时，手机号模块不可用，不会自动清空绑定或重建指纹。

新加密密钥可以使用新 ID 加入 keyring，并改 active ID；新数据用新密钥，旧数据仍用历史密钥读取。
不要删去当前数据库（包括保留期内的认证记录）或仍需恢复的历史备份使用的密钥。
本期不自动重加密，也不支持在线更换查询密钥。查询密钥轮换需另行停用模块、离线迁移
全部指纹与校验信息，不能仅改环境配置。

数据库备份只含密文及指纹，应与密钥配置分开保管；恢复时使用配套 keyring 和查询密钥。
丢失密钥无法恢复对应号码。运行中的服务需要在内存取得号码才能向阿里云发送/核验短信。

## 故障与限流

功能关闭、密钥/参数缺失或供应商故障不影响核心启动、健康检查、登录和项目/任务/AI。
已绑定且密钥正常时即使关闭发送功能也可查看；密钥不可用时显示已绑定但号码暂不可读取。

发送和核验同用户互斥，同号码在途操作也互斥。新发送获准后旧挑战失效。
验证码 300 秒有效、60 秒重发，每挑战最多 5 次提交（含错误密码）；配额按用户、号码、全局分别累计。
失败/不确定发送仍计数，重启不清零。认证记录保留至少完整 24 小时窗口；超过 48 小时后在新操作时
分批清理。操作期限 30 秒，超期记录按失败处理，迟到响应不能覆盖新操作。

模块独立两个工作线程和并发槽，满载立即拒绝；云调用连接 2 秒、读取 5 秒超时，关闭自动重试。
发送超时可能已经发出短信，等待冷却后主动重试。图形凭证只能用一次，重发需重新验证。
云核验后若个人资料同时被修改或数据库提交失败，保留原号码并重新认证。
日志、审计及错误响应不会包含号码、验证码、密码、密钥或供应商请求正文。

## 接口

- `GET /api/v1/profile/phone`：本人状态、脱敏号码、认证时间、revision、冷却及公开图形配置。
- `POST /api/v1/profile/phone/challenges`：phone_number、captcha_verify_param；返回 challenge_id、expires_at、retry_after。
- `POST /api/v1/profile/phone/challenges/{id}/verify`：sms_code、revision，换绑额外 current_password。

接口要求有效登录，写请求要求 CSRF；核验记录绑定当前用户及登录会话。
通用 UserOut、组织目录及管理接口没有手机号字段。审计仅包含操作和结果。

## 回滚

优先设置 `MVP_PHONE_VERIFICATION_ENABLED=false` 并重启后端，保留加密数据。
完整代码回滚必须按整版发布记录操作。移除该迁移时先停服并备份，再使用当前工具执行
`alembic downgrade f8a1b2c3d4e5`（SQLite >= 3.35）：该操作永久删除手机号、认证和密钥校验数据，
但不删除用户。恢复旧备份会丢失备份之后的业务写入，应按现有恢复流程处理。
新 SDK 及传递依赖已锁定；离线代码 bundle 不包含依赖制品，需另外准备 Python 依赖缓存。
