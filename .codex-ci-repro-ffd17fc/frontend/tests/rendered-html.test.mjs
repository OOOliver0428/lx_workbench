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
  assert.match(
    response.headers.get("content-security-policy") ?? "",
    /frame-ancestors 'none'/,
  );
  assert.equal(response.headers.get("x-frame-options"), "DENY");
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.equal(response.headers.get("referrer-policy"), "no-referrer");

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
    dashboardView,
    authView,
    aiConfig,
    projectsView,
    tasksView,
    recordsView,
    weeklyReportsView,
    adminView,
    layout,
    packageJson,
    envExample,
    apiProxy,
    nextConfig,
    globalStyles,
    dateUtils,
    objectPermissions,
  ] =
    await Promise.all([
      readFile(new URL("../app/api.ts", import.meta.url), "utf8"),
      readFile(new URL("../app/workspace-app.tsx", import.meta.url), "utf8"),
      readFile(
        new URL("../app/components/app-shell.tsx", import.meta.url),
        "utf8",
      ),
      readFile(
        new URL("../app/components/dashboard-view.tsx", import.meta.url),
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
      readFile(
        new URL("../app/components/weekly-reports-view.tsx", import.meta.url),
        "utf8",
      ),
      readFile(
        new URL("../app/components/admin-view.tsx", import.meta.url),
        "utf8",
      ),
      readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
      readFile(new URL("../package.json", import.meta.url), "utf8"),
      readFile(new URL("../.env.example", import.meta.url), "utf8"),
      readFile(
        new URL("../app/api/[...path]/route.ts", import.meta.url),
        "utf8",
      ),
      readFile(new URL("../next.config.ts", import.meta.url), "utf8"),
      readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
      readFile(new URL("../app/date-utils.ts", import.meta.url), "utf8"),
      readFile(new URL("../app/object-permissions.ts", import.meta.url), "utf8"),
    ]);

  assert.match(api, /credentials:\s*"include"/);
  assert.match(api, /NEXT_PUBLIC_API_BASE_URL\s*\?\?\s*""/);
  assert.match(api, /X-CSRF-Token/);
  assert.match(api, /request_id/);
  assert.match(api, /response\.status === 401/);
  assert.match(api, /setSessionInvalidatedHandler/);
  assert.match(api, /normalizeAuthContext/);
  assert.match(api, /Array\.isArray\(context\.permissions\)/);
  assert.match(api, /\/api\/v1\/ai\/chat/);
  assert.match(api, /\/api\/v1\/ai\/configuration\/test/);
  assert.match(api, /\/api\/v1\/users\/permissions\/catalog/);
  assert.match(api, /\/api\/v1\/users\/\$\{id\}\/permissions/);
  assert.match(api, /\/api\/v1\/audit-events\?limit=100/);
  assert.match(api, /method:\s*"PUT"/);
  assert.match(appShell, /window\.confirm/);
  assert.match(appShell, /onClick=\{confirmLogout\}/);
  assert.match(appShell, /aria-label="打开 AI 助手"/);
  assert.match(appShell, /sidebarCollapsed/);
  assert.match(appShell, /className="sidebar-toggle"/);
  assert.match(appShell, /aria-pressed=\{sidebarCollapsed\}/);
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
  assert.match(app, /DashboardView/);
  assert.match(app, /activeView === "dashboard"/);
  assert.match(app, /auth\.permissions/);
  assert.match(appShell, /label:\s*"作战台"/);
  assert.match(appShell, /dashboard\.opportunity\.view/);
  assert.match(appShell, /settings\.users\.manage/);
  assert.match(dashboardView, /商机进展状态，一屏看清/);
  assert.match(dashboardView, /人在、产出在、进展在/);
  assert.match(dashboardView, /跨周趋势与团队节奏/);
  assert.match(dashboardView, /api\.dashboard\.recordProgress/);
  assert.match(dashboardView, /dashboard\.opportunities/);
  assert.match(dashboardView, /dashboard\.opportunity\.progress/);
  assert.match(dashboardView, /dashboard\.opportunity\.create/);
  assert.match(dashboardView, /新建商机/);
  assert.match(dashboardView, /创建并关联项目/);
  assert.match(dashboardView, /className="war-people-summary"/);
  assert.match(dashboardView, /person\.display_name/);
  assert.doesNotMatch(dashboardView, /人员 \/ 工时/);
  assert.doesNotMatch(dashboardView, /已关联：/);
  assert.match(api, /\/api\/v1\/opportunities/);
  assert.match(api, /convert-to-project/);
  assert.match(app, /projectCreationDraft/);
  assert.match(app, /onCreateProjectFromOpportunity/);
  assert.match(dashboardView, /api\.dashboard\.generateTeamSummary/);
  assert.match(dashboardView, /api\.tasks\.createRelation/);
  assert.match(dashboardView, /建立任务关联/);
  assert.match(dashboardView, /dashboard\.task_links/);
  assert.doesNotMatch(dashboardView, /onWheel=/);
  assert.doesNotMatch(dashboardView, /滚轮缩放/);
  assert.match(dashboardView, /按钮缩放/);
  assert.match(
    dashboardView,
    /<rect[\s\S]*?x="-72"[\s\S]*?y="-42"[\s\S]*?width="144"[\s\S]*?height="84"[\s\S]*?rx="18"/,
  );
  assert.match(globalStyles, /\.war-project-node:focus rect/);
  assert.match(dashboardView, /shortWeekLabel\(week\.label\)/);
  assert.doesNotMatch(dashboardView, /T00:00:00\+08:00/);
  assert.match(app, /TasksView/);
  assert.match(
    app,
    /<TasksView[\s\S]*?canEdit=\{permissions\.includes\("tasks\.edit"\)\}[\s\S]*?canCreate=\{permissions\.includes\("tasks\.create"\)\}[\s\S]*?currentUser=\{auth\.user\}/,
  );
  assert.match(
    app,
    /<ProjectsView[\s\S]*?canEdit=\{permissions\.includes\("projects\.edit"\)\}[\s\S]*?canCreate=\{permissions\.includes\("projects\.create"\)\}/,
  );
  assert.match(app, /RecordsView/);
  assert.match(app, /currentUser=\{auth\.user\}/);
  assert.match(
    projectsView,
    /required=\{currentUser\.role === "super_admin"\}/,
  );
  assert.match(projectsView, /请选择项目负责人/);
  assert.match(projectsView, /value=\{ownerId\}/);
  assert.match(projectsView, /api\.opportunities\.convertToProject/);
  assert.match(projectsView, /canManageProjectObject\(canEdit, currentUser, selected\)/);
  assert.match(projectsView, /api\.projects\.mergePreview/);
  assert.match(projectsView, /api\.projects\.merge\(source\.id/);
  assert.match(
    projectsView,
    /const \[allProjects,\s*setAllProjects\]\s*=\s*useState<ProjectSummary\[\]>/,
  );
  assert.match(
    projectsView,
    /const allProjectRowsRequest = params\.size[\s\S]*?\?\s*api\.projects\.list\(\)[\s\S]*?:\s*projectRowsRequest/,
  );
  assert.match(
    projectsView,
    /<ProjectMergeModal[\s\S]*?source=\{selected\}[\s\S]*?projects=\{allProjects\}/,
  );
  assert.match(projectsView, /source_revision:\s*source\.revision/);
  assert.match(projectsView, /target_revision:\s*target\.revision/);
  assert.match(projectsView, /preview\.progress_count/);
  assert.match(projectsView, /preview\.invalidated_task_relation_count/);
  assert.match(projectsView, /仅团队负责人和管理员可执行/);
  assert.match(tasksView, /canManageTaskObject\(/);
  assert.match(tasksView, /projectOwners\.get\(task\.project_id\)/);
  assert.match(tasksView, /api\.tasks\.update\(task\.id/);
  assert.match(tasksView, /api\.tasks\.reassign\(task\.id/);
  assert.match(tasksView, /请填写转派原因/);
  assert.match(tasksView, /task\.collaborator_ids\.includes\(user\.id\)/);
  assert.match(recordsView, /current_week_only/);
  assert.match(recordsView, /仅显示本周记录/);
  assert.match(adminView, /permissionClosure/);
  assert.match(adminView, /requires_team_scope/);
  assert.match(adminView, /需团队负责人及直属成员/);
  assert.match(api, /caught\.status === 409/);
  assert.match(api, /数据已被其他人更新，请刷新最新版本后重试/);
  assert.match(objectPermissions, /PRIVILEGED_ROLES/);
  assert.match(objectPermissions, /project\.owner_id === currentUser\.id/);
  assert.match(objectPermissions, /task\.owner_id === currentUser\.id/);
  assert.match(objectPermissions, /projectOwnerId === currentUser\.id/);
  assert.match(projectsView, /owner_avatar_key/);
  assert.match(projectsView, /member\.avatar_key/);
  assert.match(tasksView, /user\.avatar_key/);
  assert.match(recordsView, /author_avatar_key/);
  assert.match(recordsView, /record\.project_name/);
  assert.match(weeklyReportsView, /选择个人周报周目/);
  assert.match(weeklyReportsView, /保存草稿/);
  assert.match(weeklyReportsView, /提交周报/);
  assert.match(weeklyReportsView, /往期团队周报/);
  assert.match(weeklyReportsView, /api\.weeklyReports\.teamSummaries/);
  assert.doesNotMatch(api + weeklyReportsView, /weekly-reports\/inbox/);
  assert.match(adminView, /PermissionModal/);
  assert.match(adminView, /system_admin_assignable/);
  assert.match(adminView, /settings\.audit\.view/);
  assert.match(adminView, /审计记录/);
  assert.match(apiProxy, /MVP_INTERNAL_API_BASE_URL/);
  assert.match(apiProxy, /"cookie"/);
  assert.match(apiProxy, /"x-csrf-token"/);
  assert.match(apiProxy, /request\.arrayBuffer\(\)/);
  assert.match(apiProxy, /new Headers\(upstreamResponse\.headers\)/);
  assert.match(apiProxy, /export const POST = proxy/);
  assert.doesNotMatch(apiProxy, /"x-forwarded-for"/);
  assert.match(apiProxy, /LLM_UPSTREAM_TIMEOUT_MS\s*=\s*195_000/);
  assert.match(apiProxy, /v1\/weekly-reports\/current\/generate/);
  assert.match(apiProxy, /v1\/dashboard\/team-summary/);
  assert.match(apiProxy, /cache-control/);
  assert.match(apiProxy, /API_UPSTREAM_TIMEOUT/);
  assert.match(nextConfig, /Content-Security-Policy/);
  assert.match(nextConfig, /X-Frame-Options/);
  assert.match(nextConfig, /X-Content-Type-Options/);
  assert.match(nextConfig, /Referrer-Policy/);
  assert.match(globalStyles, /\.primary-nav\s*\{[\s\S]*?overflow-x:\s*auto/);
  assert.match(
    globalStyles,
    /\.task-card footer\s*\{[\s\S]*?flex-wrap:\s*wrap/,
  );
  assert.match(
    globalStyles,
    /\.sidebar-bottom \.account-summary \.account-logout-button[\s\S]*?height:\s*44px/,
  );
  assert.match(recordsView, /defaultValue=\{localDateInputValue\(\)\}/);
  assert.match(recordsView, /api\.records\.update\(record\.id/);
  assert.match(recordsView, /api\.records\.delete\(record\.id,\s*record\.revision/);
  assert.match(recordsView, /window\.confirm\(`确认删除/);
  assert.match(recordsView, /代编辑原因/);
  assert.match(adminView, /api\.tags\.list\(true\)/);
  assert.match(adminView, /api\.tags\.update\(tag\.id/);
  assert.match(api, /users:\s*\{[\s\S]*?list:\s*\(includeInactive = false\)/);
  assert.match(adminView, /api\.users\.list\(true\)/);
  assert.match(adminView, /确认停用标签/);
  assert.match(dateUtils, /getTimezoneOffset\(\)\s*\*\s*60_000/);
  assert.doesNotMatch(
    recordsView,
    /new Date\(\)\.toISOString\(\)\.slice\(0,\s*10\)/,
  );
  assert.match(dashboardView, /member\.weekly_minutes === null/);
  assert.match(dashboardView, /project\.weekly_minutes === null/);
  assert.match(dashboardView, /canViewWorkMetrics/);
  assert.match(dashboardView, /projectStatusLabel\(project\.lifecycle_status\)/);
  assert.match(dashboardView, /商业阶段在关联商机中独立维护/);
  assert.match(globalStyles, /html\s*\{[\s\S]*?min-width:\s*0/);
  assert.match(dashboardView, /工时不可见/);
  assert.match(envExample, /^NEXT_PUBLIC_API_BASE_URL=$/m);
  assert.match(envExample, /^MVP_INTERNAL_API_BASE_URL=http:\/\/127\.0\.0\.1:8787$/m);
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
  assert.doesNotMatch(
    api + aiConfig + envExample,
    /sk-(?:cp-)?[A-Za-z0-9_-]{20,}/,
  );
});

test("matches backend object-level project and task management rules", async () => {
  const { canManageProjectObject, canManageTaskObject } = await import(
    new URL("../app/object-permissions.ts", import.meta.url)
  );
  const member = { id: "member-1", role: "member" };
  const leader = { id: "leader-1", role: "team_leader" };

  assert.equal(
    canManageProjectObject(true, member, { owner_id: member.id }),
    true,
  );
  assert.equal(
    canManageProjectObject(true, member, { owner_id: "someone-else" }),
    false,
  );
  assert.equal(
    canManageProjectObject(true, leader, { owner_id: "someone-else" }),
    true,
  );
  assert.equal(
    canManageProjectObject(false, leader, { owner_id: leader.id }),
    false,
  );

  assert.equal(
    canManageTaskObject(
      true,
      member,
      { owner_id: member.id },
      "someone-else",
    ),
    true,
  );
  assert.equal(
    canManageTaskObject(
      true,
      member,
      { owner_id: "someone-else" },
      member.id,
    ),
    true,
  );
  assert.equal(
    canManageTaskObject(
      true,
      member,
      { owner_id: "someone-else" },
      "another-owner",
    ),
    false,
  );
  assert.equal(
    canManageTaskObject(
      false,
      leader,
      { owner_id: "someone-else" },
      "another-owner",
    ),
    false,
  );
});

test("formats work-record defaults in local time near the UTC day boundary", async () => {
  const { localDateInputValue } = await import(
    new URL("../app/date-utils.ts", import.meta.url)
  );
  const shanghaiJustAfterMidnight = {
    getTime: () => Date.parse("2026-07-30T16:30:00.000Z"),
    getTimezoneOffset: () => -480,
  };
  assert.equal(localDateInputValue(shanghaiJustAfterMidnight), "2026-07-31");
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
