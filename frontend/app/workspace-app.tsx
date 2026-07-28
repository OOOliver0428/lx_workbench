"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api,
  setCsrfToken,
  setSessionInvalidatedHandler,
} from "./api";
import { AdminView } from "./components/admin-view";
import { AppShell, type WorkspaceView } from "./components/app-shell";
import { LoginView, PasswordChangeGate } from "./components/auth-view";
import { ProjectsView } from "./components/projects-view";
import { ProfileSettingsView } from "./components/profile-settings-view";
import { RecordsView } from "./components/records-view";
import { TasksView } from "./components/tasks-view";
import { WeeklyReportsView } from "./components/weekly-reports-view";
import type { AuthContext } from "./types";

export function WorkspaceApp() {
  const [auth, setAuth] = useState<AuthContext | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [activeView, setActiveView] = useState<WorkspaceView>("projects");
  const [loginNotice, setLoginNotice] = useState("");

  const invalidateSession = useCallback((message: string) => {
    setCsrfToken("");
    setAuth(null);
    setActiveView("projects");
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
      setActiveView("projects");
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
        }}
      />
    );
  }
  if (auth.user.must_change_password) {
    return <PasswordChangeGate context={auth} onChanged={setAuth} />;
  }

  return (
    <AppShell
      context={auth}
      activeView={activeView}
      onViewChange={setActiveView}
      onLogout={logout}
    >
      {activeView === "projects" ? <ProjectsView /> : null}
      {activeView === "tasks" ? <TasksView /> : null}
      {activeView === "records" ? <RecordsView /> : null}
      {activeView === "reports" ? (
        <WeeklyReportsView role={auth.user.role} />
      ) : null}
      {activeView === "profile" ? (
        <ProfileSettingsView
          context={auth}
          onContextChange={setAuth}
        />
      ) : null}
      {activeView === "admin" ? <AdminView /> : null}
    </AppShell>
  );
}
