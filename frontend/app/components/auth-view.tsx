"use client";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiClientError, setCsrfToken } from "../api";
import type { AuthContext } from "../types";
import { InlineNotice } from "./ui";
import loginArtwork from "../login-artwork.json";

export function LoginView({
  notice,
  onAuthenticated,
}: {
  notice?: string;
  onAuthenticated: (context: AuthContext) => void;
}) {
  const [loginIdentifier, setLoginIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const artworkRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const artwork = artworkRef.current;
    if (!artwork) return;
    const motion = window.matchMedia("(hover: hover) and (pointer: fine) and (min-width: 861px) and (prefers-reduced-motion: no-preference)");
    const planes = Array.from(artwork.querySelectorAll<HTMLElement>(".login-screen-plane"));
    let frame = 0;
    let pointer: { x: number; y: number } | null = null;
    const reset = () => {
      cancelAnimationFrame(frame);
      frame = 0;
      pointer = null;
      for (const plane of planes) {
        plane.style.removeProperty("--hover-x");
        plane.style.removeProperty("--hover-y");
        plane.style.removeProperty("--hover-depth");
      }
    };
    const update = () => {
      frame = 0;
      if (!pointer || !motion.matches) return;
      const bounds = artwork.getBoundingClientRect();
      const x = Math.max(-1, Math.min(1, (pointer.x - bounds.left) / bounds.width * 2 - 1));
      const y = Math.max(-1, Math.min(1, (pointer.y - bounds.top) / bounds.height * 2 - 1));
      const active = document.elementFromPoint(pointer.x, pointer.y)?.closest(".login-screen-plane");
      planes.forEach((plane, index) => {
        const weight = plane === active ? 1 : 0.25;
        const amplitude = (6 - index * 0.6) * weight;
        plane.style.setProperty("--hover-x", `${x * amplitude}px`);
        plane.style.setProperty("--hover-y", `${y * amplitude - weight * 4}px`);
        plane.style.setProperty("--hover-depth", String(weight));
      });
    };
    const move = (event: PointerEvent) => {
      if (!motion.matches || event.pointerType !== "mouse") return;
      pointer = { x: event.clientX, y: event.clientY };
      if (!frame) frame = requestAnimationFrame(update);
    };
    artwork.addEventListener("pointermove", move, { passive: true });
    artwork.addEventListener("pointerleave", reset);
    artwork.addEventListener("pointercancel", reset);
    motion.addEventListener("change", reset);
    window.addEventListener("blur", reset);
    return () => {
      reset();
      artwork.removeEventListener("pointermove", move);
      artwork.removeEventListener("pointerleave", reset);
      artwork.removeEventListener("pointercancel", reset);
      motion.removeEventListener("change", reset);
      window.removeEventListener("blur", reset);
    };
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const context = await api.auth.login(loginIdentifier, password);
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
      <section className="login-story" ref={artworkRef} aria-hidden="true">
        <div className="login-artwork" style={{ backgroundImage: `url(${loginArtwork["blue-ribbon-v3"]})` }}>
          <div className="login-plane-stack">
            {(["opportunities", "tasks", "work", "reports"] as const).map((screen) => (
              <div className="login-screen-plane" key={screen}>
                {/* The frame and uncropped screenshot share the stack transform. */}
                <div className="login-screen-surface" style={{ backgroundImage: `url(${loginArtwork[screen]})` }} />
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="login-panel">
        <form className="login-card" onSubmit={submit}>
          <header>
            <div className="login-brand">
              <span className="brand-symbol" aria-hidden="true"><i /><i /><i /></span>
              <span>协作工作台</span>
            </div>
            <h2>登录工作台</h2>
            <p>把握商机，让协作有序向前。</p>
          </header>
          {notice ? <InlineNotice tone="warning">{notice}</InlineNotice> : null}
          {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
          <label className="field">
            <span>账号</span>
            <input
              value={loginIdentifier}
              onChange={(event) => setLoginIdentifier(event.target.value)}
              placeholder="输入登录名或显示名称"
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
            {submitting ? "正在验证…" : "登录"}
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
