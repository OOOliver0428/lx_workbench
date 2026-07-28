import assert from "node:assert/strict";
import { readFile, stat } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: handler } = await import(workerUrl.href);
  const request = new Request("http://localhost/", {
    headers: { accept: "text/html" },
  });
  if (typeof handler === "function") {
    return handler(request);
  }
  return handler.fetch(request);
}

test("server-renders the collaboration workspace shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<html[^>]+lang="zh-CN"/i);
  assert.match(html, /<title>协作工作台<\/title>/i);
  assert.match(html, /boot-screen/);
  assert.match(html, /正在进入团队空间/);
  assert.doesNotMatch(html, /react-loading-skeleton|_sites-preview/);
});

test("keeps the API contract and AI secret boundary explicit", async () => {
  const [
    api,
    app,
    appShell,
    authView,
    aiConfig,
    projectsView,
    tasksView,
    recordsView,
    layout,
    packageJson,
    envExample,
  ] =
    await Promise.all([
    readFile(new URL("../app/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/workspace-app.tsx", import.meta.url), "utf8"),
    readFile(
      new URL("../app/components/app-shell.tsx", import.meta.url),
      "utf8",
    ),
    readFile(
      new URL("../app/components/auth-view.tsx", import.meta.url),
      "utf8",
    ),
    readFile(
      new URL("../app/components/ai-config-panel.tsx", import.meta.url),
      "utf8",
    ),
    readFile(
      new URL("../app/components/projects-view.tsx", import.meta.url),
      "utf8",
    ),
    readFile(
      new URL("../app/components/tasks-view.tsx", import.meta.url),
      "utf8",
    ),
    readFile(
      new URL("../app/components/records-view.tsx", import.meta.url),
      "utf8",
    ),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
    readFile(new URL("../.env.example", import.meta.url), "utf8"),
    ]);

  assert.match(api, /credentials:\s*"include"/);
  assert.match(api, /X-CSRF-Token/);
  assert.match(api, /request_id/);
  assert.match(api, /response\.status === 401/);
  assert.match(api, /setSessionInvalidatedHandler/);
  assert.match(api, /\/api\/v1\/ai\/chat/);
  assert.match(api, /\/api\/v1\/ai\/configuration\/test/);
  assert.match(api, /method:\s*"PUT"/);
  assert.match(appShell, /window\.confirm/);
  assert.match(appShell, /onClick=\{confirmLogout\}/);
  assert.match(appShell, /<strong>AI 助手<\/strong>/);
  assert.match(appShell, /赋能售前和解决方案/);
  assert.match(authView, /赋能售前和解决方案/);
  assert.doesNotMatch(appShell + authView, /Solution Workspace/);
  assert.doesNotMatch(appShell, /MiniMax 助手|MINIMAX COPILOT/);
  assert.match(appShell, /messages\.map\(\(message\)/);
  assert.match(
    appShell,
    /setPrompt\(""\)[\s\S]*?api\.ai\.chat\(question\)/,
  );
  assert.match(appShell, /关闭窗口后清空本次对话/);
  assert.doesNotMatch(appShell, /setAnswer|localStorage|sessionStorage/);
  assert.match(aiConfig, /测试不会自动写入系统配置/);
  assert.match(aiConfig, /Token Plan Key 与按量计费 API Key/);
  assert.match(aiConfig, /access_mode/);
  assert.match(aiConfig, /disabled=\{!testResult/);
  assert.match(aiConfig, /type="password"/);
  assert.doesNotMatch(aiConfig, /localStorage|sessionStorage/);
  assert.match(app, /ProjectsView/);
  assert.match(app, /TasksView/);
  assert.match(app, /RecordsView/);
  assert.match(projectsView, /owner_avatar_key/);
  assert.match(projectsView, /member\.avatar_key/);
  assert.match(tasksView, /user\.avatar_key/);
  assert.match(recordsView, /author_avatar_key/);
  assert.doesNotMatch(
    projectsView + tasksView + recordsView,
    /display_name\.slice\(0,\s*1\)/,
  );
  assert.match(app, /auth\.expires_at/);
  assert.match(app, /invalidateSession/);
  assert.match(app, /window\.setTimeout/);
  assert.match(
    app,
    /async function logout\(\)[\s\S]*?catch\s*\{[\s\S]*?finally\s*\{[\s\S]*?setAuth\(null\)/,
  );
  assert.match(layout, /title:\s*"协作工作台"/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  assert.match(envExample, /NEXT_PUBLIC_API_BASE_URL=http:\/\/127\.0\.0\.1:8787/);
  assert.doesNotMatch(
    api + aiConfig + envExample,
    /sk-(?:cp-)?[A-Za-z0-9_-]{20,}/,
  );
});

test("ships the normalized preset avatar catalog", async () => {
  const catalog = JSON.parse(
    await readFile(
      new URL("../public/avatars/catalog.json", import.meta.url),
      "utf8",
    ),
  );
  assert.equal(catalog.length, 56);
  assert.equal(new Set(catalog.map((item) => item.id)).size, 56);
  assert.deepEqual(
    new Set(catalog.map((item) => item.style)),
    new Set([
      "flat",
      "clay-soft",
      "pixel-soft",
      "paper",
      "line",
      "pixel",
      "clay",
    ]),
  );

  for (const avatar of catalog) {
    const avatarUrl = new URL(`../public${avatar.url}`, import.meta.url);
    const file = await stat(avatarUrl);
    const metadata = await sharp(fileURLToPath(avatarUrl)).metadata();
    assert.ok(file.size > 0);
    assert.ok(file.size < 100_000);
    assert.equal(metadata.width, 512);
    assert.equal(metadata.height, 512);
    assert.equal(metadata.format, "webp");
  }
});
