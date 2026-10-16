"use client";

import { useEffect, useRef, useState } from "react";
import { ApiClientError, request } from "../api";
import type { AuthContext } from "../types";
import {
  captchaWindow, loadCaptcha, remainingSeconds, validPhone,
} from "../phone-verification";
import type { CaptchaInstance, PhoneChallenge, PhoneStatus } from "../phone-verification";
import { InlineNotice, Modal } from "./ui";

const PHONE_URL = "/api/v1/profile/phone";
function message(error: unknown): string {
  return error instanceof Error ? error.message : "手机号认证暂不可用";
}

export function PhoneSettingsCard({ context, onContextChange }: {
  context: AuthContext;
  onContextChange: (context: AuthContext) => void;
}) {
  const [status, setStatus] = useState<PhoneStatus | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState(false);
  const [opening, setOpening] = useState(false);
  useEffect(() => {
    let alive = true;
    request<PhoneStatus>(PHONE_URL).then((result) => {
      if (alive) setStatus(result);
    }).catch(() => { if (alive) setError("手机号服务暂不可用，其他功能可继续使用。"); });
    return () => { alive = false; };
  }, [context.user.id]);

  async function openDialog() {
    setOpening(true); setError(""); setSaved(false);
    try {
      const latest = await request<PhoneStatus>(PHONE_URL);
      setStatus(latest);
      if (latest.availability === "ready") setOpen(true);
    } catch (caught) { setError(message(caught)); }
    finally { setOpening(false); }
  }

  if (!status && !error) return null;
  if (status?.availability === "disabled" && !status.bound) return null;
  return (
    <section className="settings-card phone-settings-card">
      <header><div><p className="eyebrow">PHONE VERIFICATION</p><h2>手机号</h2>
        <p>绑定已验证的手机号，作为后续身份关联的联系方式。</p></div></header>
      {status?.bound ? <p>{status.phone_masked ?? "已绑定，号码暂不可读取"}
        {status.verified_at ? <small> · 认证于 {new Date(status.verified_at).toLocaleDateString("zh-CN")}</small> : null}
      </p> : <p>尚未绑定手机号，不影响当前功能使用。</p>}
      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
      {saved ? <InlineNotice>手机号已更新。</InlineNotice> : null}
      {status?.availability === "unavailable" ? <InlineNotice>手机号认证暂不可用，请稍后重试。</InlineNotice> : null}
      {status?.availability === "ready" ? <button type="button" disabled={opening} onClick={() => void openDialog()}>
        {status.bound ? "更换手机号" : "绑定手机号"}
      </button> : null}
      {open && status ? <PhoneBindingDialog initial={status} onClose={() => setOpen(false)} onSaved={(result) => {
        setStatus(result); setOpen(false); setSaved(true);
        onContextChange({ ...context, user: { ...context.user, revision: result.revision } });
      }} /> : null}
    </section>
  );
}

function PhoneBindingDialog({ initial, onClose, onSaved }: {
  initial: PhoneStatus;
  onClose: () => void;
  onSaved: (status: PhoneStatus) => void;
}) {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState(initial);
  const [challenge, setChallenge] = useState<PhoneChallenge | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [sdkReady, setSdkReady] = useState(false);
  const [cycle, setCycle] = useState(0);
  const [deadline, setDeadline] = useState(() => Date.now() + initial.retry_after * 1000);
  const [now, setNow] = useState(Date.now);
  const submittedPhone = useRef("");
  const alive = useRef(true);
  const inFlight = useRef(false);
  const instance = useRef<CaptchaInstance | null>(null);
  const cooling = remainingSeconds(deadline, now);
  const expired = challenge ? Date.parse(challenge.expires_at) <= now : false;

  useEffect(() => {
    alive.current = true;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => { alive.current = false; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    let disposed = false;
    let readyTimer: number | undefined;
    const config = initial.captcha;
    if (!config) return;
    function release() {
      if (!disposed && alive.current) { setBusy(false); inFlight.current = false; }
    }
    loadCaptcha({ region: config.region, prefix: config.prefix }).then(() => {
      if (disposed) return;
      captchaWindow().initAliyunCaptcha?.({
        SceneId: config.scene_id, mode: "popup", element: "#phone-captcha-element",
        button: "#phone-captcha-button", slideStyle: { width: 320, height: 40 },
        getInstance: (value: CaptchaInstance) => {
          if (disposed) { value.hide?.(); value.destroyCaptcha?.(); return; }
          instance.current = value;
          // Official SDK recommends allowing at least two seconds for initialization.
          readyTimer = window.setTimeout(() => { if (!disposed) setSdkReady(true); }, 2100);
        },
        onClose: (reason: string) => { if (reason === "userDismiss") release(); },
        onError: () => { if (!disposed) { setError("图形验证加载失败，请稍后重试"); release(); } },
        success: async (token: string) => {
          if (disposed || !alive.current || !inFlight.current) return;
          inFlight.current = false;
          setSdkReady(false);
          setChallenge(null);
          setCode("");
          try {
            const result = await request<PhoneChallenge>(PHONE_URL + "/challenges", {
              method: "POST", body: JSON.stringify({ phone_number: submittedPhone.current, captcha_verify_param: token }),
            });
            if (!disposed && alive.current) {
              setChallenge(result); setDeadline(Date.now() + result.retry_after * 1000);
            }
          } catch (caught) {
            if (!disposed && alive.current) {
              setError(message(caught));
              try {
                const latest = await request<PhoneStatus>(PHONE_URL);
                if (!disposed && alive.current) { setStatus(latest); setDeadline(Date.now() + latest.retry_after * 1000); }
              } catch { /* Main error remains visible. */ }
            }
          } finally {
            if (!disposed && alive.current) { setBusy(false); setCycle((value) => value + 1); }
          }
        },
      });
    }).catch((caught) => { if (!disposed) { setError(message(caught)); release(); } });
    return () => {
      disposed = true;
      window.clearTimeout(readyTimer);
      instance.current?.hide?.();
      instance.current?.destroyCaptcha?.();
      instance.current = null;
    };
  }, [initial.captcha, cycle]);

  async function confirm() {
    if (!challenge || busy) return;
    setBusy(true); setError("");
    try {
      const result = await request<PhoneStatus>(PHONE_URL + `/challenges/${challenge.challenge_id}/verify`, {
        method: "POST", body: JSON.stringify({ sms_code: code, revision: status.revision,
          ...(status.bound ? { current_password: password } : {}) }),
      });
      if (alive.current) onSaved(result);
    } catch (caught) {
      if (alive.current) {
        setError(message(caught));
        if (caught instanceof ApiClientError && caught.status === 409) {
          const latest = await request<PhoneStatus>(PHONE_URL).catch(() => null);
          if (latest && alive.current) setStatus(latest);
        }
      }
    } finally { if (alive.current) setBusy(false); }
  }

  return <Modal title={status.bound ? "更换手机号" : "绑定手机号"} onClose={onClose}>
    <form className="phone-binding-form" onSubmit={(event) => { event.preventDefault(); void confirm(); }}>
      <p>{status.bound ? "新号码认证成功后才会替换当前号码。" : "仅支持中国大陆手机号，同一号码只能绑定一个账号。"}</p>
      <label>手机号（+86）<input type="tel" autoComplete="tel-national" value={phone} disabled={busy}
        maxLength={14} onChange={(event) => { setPhone(event.target.value); setChallenge(null); setCode(""); setError(""); }} /></label>
      <div id="phone-captcha-element" />
      <button id="phone-captcha-button" type="button" disabled={!sdkReady || busy || cooling > 0 || !validPhone(phone)}
        onClickCapture={() => { submittedPhone.current = phone.trim(); inFlight.current = true; setBusy(true); setError(""); }}>
        {cooling > 0 ? `${cooling} 秒后可重发` : !sdkReady ? "正在准备图形验证…" : "发送短信验证码"}
      </button>
      {!sdkReady && error ? <button type="button" disabled={busy} onClick={() => { setError(""); setCycle((value) => value + 1); }}>重试图形验证</button> : null}
      {challenge ? <InlineNotice>{expired ? "验证码已过期，请重新发送。" : "短信已发送，验证码 5 分钟内有效。"}</InlineNotice> : null}
      <label>短信验证码<input inputMode="numeric" autoComplete="one-time-code" value={code}
        maxLength={6} disabled={busy || !challenge} onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))} /></label>
      {status.bound ? <label>当前登录密码<input type="password" autoComplete="current-password" value={password}
        maxLength={256} disabled={busy} onChange={(event) => setPassword(event.target.value)} /></label> : null}
      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
      <button type="submit" disabled={busy || !challenge || expired || code.length !== 6 || (status.bound && !password)}>
        {busy ? "正在处理…" : "确认绑定"}
      </button>
    </form>
  </Modal>;
}
