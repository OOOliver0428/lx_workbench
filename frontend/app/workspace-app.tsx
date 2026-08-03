"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api,
  setCsrfToken,
  setSessionInvalidatedHandler,
} from "./api";
import { AdminView } from "./components/admin-view";
import {
  AppShell,
  defaultWorkspaceView,
  type WorkspaceView,
} from "./components/app-shell";
import { LoginView, PasswordChangeGate } from "./components/auth-view";
import { DashboardView } from "./components/dashboard-view";
import { ProjectsView } from "./components/projects-view";
import { ProfileSettingsView } from "./components/profile-settings-view";
import { RecordsView } from "./components/records-view";
import { TasksView } from "./components/tasks-view";
import { WeeklyReportsView } from "./components/weekly-reports-view";
import type { AuthContext, ProjectCreationDraft } from "./types";

export function WorkspaceApp() {
  const [auth, setAuth] = useState<AuthContext | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [activeView, setActiveView] = useState<WorkspaceView>("dashboard");
  const [loginNotice, setLoginNotice] = useState("");
  const [projectCreationDraft, setProjectCreationDraft] =
    useState<ProjectCreationDraft | null>(null);

  const invalidateSession = useCallback((message: string) => {
    setCsrfToken("");
    setAuth(null);
    setActiveView("dashboard");
    setLoginNotice(message || "会话已失效，请重新登录。");
  }, []);

  useEffect(() => {
    setSessionInvalidatedHandler(invalidateSession);
    return () => setSessionInvalidatedHandler(null);
  }, [invalidateSession]);

  useEffect(() => {
    api.auth
      .me()
      .then((context) => {
        setCsrfToken(context.csrf_token);
        setAuth(context);
        setActiveView(defaultWorkspaceView(context));
        setLoginNotice("");
      })
      .catch(() => setAuth(null))
      .finally(() => setCheckingSession(false));
  }, []);

  useEffect(() => {
    if (!auth) return;
    const expiresAt = Date.parse(auth.expires_at);
    if (!Number.isFinite(expiresAt)) return;
    const remainingMilliseconds = Math.max(expiresAt - Date.now(), 0);
    const timeout = window.setTimeout(
      () => invalidateSession("会话已到期，请重新登录。"),
      remainingMilliseconds,
    );
    return () => window.clearTimeout(timeout);
  }, [auth, invalidateSession]);

  async function logout() {
    try {
      await api.auth.logout();
    } catch {
      // Logout is best effort: a network failure must not trap the user in an
      // expired local session or surface an unhandled promise rejection.
    } finally {
      setCsrfToken("");
      setAuth(null);
      setActiveView("dashboard");
      setLoginNotice("");
    }
  }

  if (checkingSession) {
    return (
      <main className="boot-screen">
        <div className="boot-mark">
          <i />
          <i />
          <i />
        </div>
        <p>正在进入团队空间…</p>
      </main>
    );
  }
  if (!auth) {
    return (
      <LoginView
        notice={loginNotice}
        onAuthenticated={(context) => {
          setLoginNotice("");
          setAuth(context);
          setActiveView(defaultWorkspaceView(context));
        }}
      />
    );
  }
  if (auth.user.must_change_password) {
    return (
      <PasswordChangeGate
        context={auth}
        onChanged={(context) => {
          setAuth(context);
          setActiveView(defaultWorkspaceView(context));
        }}
      />
    );
  }

  const permissions = auth.permissions ?? [];

  return (
    <AppShell
      context={auth}
      activeView={activeView}
      onViewChange={setActiveView}
      onLogout={logout}
    >
      {activeView === "dashboard" ? (
        <DashboardView
          permissions={permissions}
          currentUser={auth.user}
          onCreateProjectFromOpportunity={(draft) => {
            setProjectCreationDraft(draft);
            setActiveView("projects");
          }}
        />
      ) : null}
      {activeView === "projects" ? (
        <ProjectsView
          canEdit={permissions.includes("projects.edit")}
          canCreate={permissions.includes("projects.create")}
          currentUser={auth.user}
          creationDraft={projectCreationDraft}
          onCreationDraftHandled={() => setProjectCreationDraft(null)}
        />
      ) : null}
      {activeView === "tasks" ? (
        <TasksView
          canEdit={permissions.includes("tasks.edit")}
          canCreate={permissions.includes("tasks.create")}
          currentUser={auth.user}
        />
      ) : null}
      {activeView === "records" ? (
        <RecordsView
          canManage={permissions.includes("work_records.manage")}
          canViewProjects={permissions.includes("projects.view")}
          canViewTasks={permissions.includes("tasks.view")}
        />
      ) : null}
      {activeView === "reports" ? (
        <WeeklyReportsView
          canManage={permissions.includes("weekly_reports.manage")}
          canViewTeamReports={permissions.includes(
            "dashboard.team_summary.generate",
          )}
        />
      ) : null}
      {activeView === "profile" ? (
        <ProfileSettingsView
          context={auth}
          onContextChange={setAuth}
        />
      ) : null}
      {activeView === "admin" ? <AdminView context={auth} /> : null}
    </AppShell>
  );
}
