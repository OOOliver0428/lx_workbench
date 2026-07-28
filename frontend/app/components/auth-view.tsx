"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { api, ApiClientError, setCsrfToken } from "../api";
import type { AuthContext } from "../types";
import { InlineNotice } from "./ui";

export function LoginView({
  notice,
  onAuthenticated,
}: {
  notice?: string;
  onAuthenticated: (context: AuthContext) => void;
}) {
  const [loginName, setLoginName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const context = await api.auth.login(loginName, password);
      setCsrfToken(context.csrf_token);
      onAuthenticated(context);
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "暂时无法登录，请稍后重试",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-story">
        <div className="brand-lockup brand-lockup-light">
          <span className="brand-symbol">
            <i />
            <i />
            <i />
          </span>
          <span>
            <strong>协作工作台</strong>
            <small>赋能售前和解决方案</small>
          </span>
        </div>
        <div className="story-copy">
          <h1>
            跨部门级协作作战台，
            <br />
            把握商机，掌控节奏
          </h1>
          <p>
            当前为MVP版本，仅保留最小化功能，试运行期间收集问题，后续功能会持续迭代。
          </p>
        </div>
        <div className="story-footnote">
          <span>内网试运行版</span>
          <i />
          <span>数据仅保存在本地服务</span>
        </div>
      </section>

      <section className="login-panel">
        <form className="login-card" onSubmit={submit}>
          <header>
            <span className="mobile-brand">协作工作台</span>
            <p className="eyebrow">WELCOME BACK</p>
            <h2>登录团队空间</h2>
            <p>使用管理员分配的本地账号进入。</p>
          </header>
          {notice ? <InlineNotice tone="warning">{notice}</InlineNotice> : null}
          {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
          <label className="field">
            <span>登录名</span>
            <input
              value={loginName}
              onChange={(event) => setLoginName(event.target.value)}
              placeholder="例如 zhangsan"
              autoComplete="username"
              required
              autoFocus
            />
          </label>
          <label className="field">
            <span>密码</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="输入密码"
              autoComplete="current-password"
              required
            />
          </label>
          <button className="primary-button login-submit" disabled={submitting}>
            {submitting ? "正在验证…" : "进入工作台"}
          </button>
          <p className="login-hint">首次登录后，系统会要求修改初始密码。</p>
        </form>
      </section>
    </main>
  );
}

export function PasswordChangeGate({
  context,
  onChanged,
}: {
  context: AuthContext;
  onChanged: (context: AuthContext) => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmedPassword, setConfirmedPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (newPassword !== confirmedPassword) {
      setError("两次输入的新密码不一致");
      return;
    }
    setError("");
    setSubmitting(true);
    try {
      await api.auth.changePassword(currentPassword, newPassword);
      const refreshed = await api.auth.me();
      setCsrfToken(refreshed.csrf_token);
      onChanged(refreshed);
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "密码修改失败",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="password-page">
      <section className="password-card">
        <div className="password-mark" aria-hidden="true">
          <span>01</span>
        </div>
        <p className="eyebrow">ACCOUNT SECURITY</p>
        <h1>设置你的正式密码</h1>
        <p className="password-lead">
          你好，{context.user.display_name}。首次进入需要先替换管理员分配的初始密码，
          新密码至少5位。
        </p>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <form onSubmit={submit}>
          <label className="field">
            <span>当前初始密码</span>
            <input
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
            />
          </label>
          <div className="form-grid">
            <label className="field">
              <span>新密码</span>
              <input
                type="password"
                minLength={5}
                autoComplete="new-password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                required
              />
            </label>
            <label className="field">
              <span>确认新密码</span>
              <input
                type="password"
                minLength={5}
                autoComplete="new-password"
                value={confirmedPassword}
                onChange={(event) => setConfirmedPassword(event.target.value)}
                required
              />
            </label>
          </div>
          <button className="primary-button" disabled={submitting}>
            {submitting ? "正在保存…" : "保存并继续"}
          </button>
        </form>
      </section>
    </main>
  );
}
