# 协作工作台前端

现代化内网 MVP 前端，使用 React 19、Vinext 和 TypeScript。当前实现项目、任务、工作记录与基础管理；
按产品约定暂不实现作战台首页和图表。

## 本地启动

后端先运行在 `127.0.0.1:8787`，然后执行：

```powershell
Copy-Item .env.example .env.local
npm install
npm run dev
```

默认请求 `http://127.0.0.1:8787`，开发服务器固定使用 `http://127.0.0.1:5174`。如果需要
修改端口，后端 `.env` 的 `MVP_CORS_ORIGINS_CSV` 也必须包含新的前端地址。

## 验证

```powershell
npm run lint
npm test
```

`npm test` 会执行生产构建，并验证 SSR 页面、Session/CSRF 契约和 AI 密钥边界。
