"use client";

import { useEffect, useRef, useState } from "react";
import { ApiClientError, request } from "../api";
import type { AuthContext } from "../types";
import {
  captchaWindow, captchaWarmupRemaining, createCaptchaLifecycle, loadCaptcha, remainingSeconds, validPhone,
} from "../phone-verification";
import type { PhoneChallenge, PhoneStatus } from "../phone-verification";
import { Check, Send, Smartphone } from "./icons";
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
      if (alive && result.availability === "ready" && result.captcha) {
        // Warm the shared SDK while the user reads settings; opening retries failures.
        void loadCaptcha({ region: result.captcha.region, prefix: result.captcha.prefix }).catch(() => {});
      }
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
  const bound = status?.bound ?? false;
  const statusDescription = bound
    ? `当前账号已关联此号码。${status?.verified_at ? ` 认证于 ${new Date(status.verified_at).toLocaleDateString("zh-CN")}。` : ""}`
    : "绑定后作为后续身份关联的联系方式，不影响当前登录方式。";
  return (
    <section className="settings-card phone-settings-card">
      <header>
        <div><p className="eyebrow">PHONE VERIFICATION</p><h2>手机号绑定</h2>
          <p>绑定已验证的手机号，作为后续身份关联的联系方式。</p></div>
        <span className="security-mark" aria-hidden="true"><Smartphone size={24} /></span>
      </header>
      <div className="phone-settings-body">
        {status ? <div className="phone-settings-summary">
          <span className={`phone-status-icon${bound ? " is-bound" : ""}`} aria-hidden="true">
            {bound ? <Check size={21} /> : <Smartphone size={21} />}
          </span>
          <div className="phone-status-copy">
            <div className="phone-status-heading">
              <strong>{bound ? status.phone_masked ?? "手机号已绑定" : "尚未绑定手机号"}</strong>
              <span className={`phone-status-badge${bound ? " is-bound" : ""}`}>
                {bound ? <Check size={12} /> : null}{bound ? "已验证" : "未绑定"}
              </span>
            </div>
            <p>{statusDescription}</p>
          </div>
        </div> : null}
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        {saved ? <InlineNotice tone="success">手机号已更新。</InlineNotice> : null}
        {status?.availability === "unavailable" ? <InlineNotice tone="warning">手机号认证暂不可用，请稍后重试。</InlineNotice> : null}
      </div>
      {status ? <footer className="settings-card-actions phone-settings-actions">
        <p>{status.bound ? "更换号码需同时验证短信和当前登录密码。" : "仅支持中国大陆手机号，同一号码只能绑定一个账号。"}</p>
        {status.availability === "ready" ? <button className="primary-button compact" type="button" disabled={opening} onClick={() => void openDialog()}>
          {opening ? "正在读取…" : status.bound ? "更换手机号" : "绑定手机号"}
        </button> : null}
      </footer> : null}
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
    let initializedAt = 0;
    const lifecycle = createCaptchaLifecycle(() => {
      window.clearTimeout(readyTimer);
      // Allow the SDK to collect initialization data before verification.
      readyTimer = window.setTimeout(() => { if (!disposed) setSdkReady(true); }, captchaWarmupRemaining(initializedAt));
    });
    function release() {
      if (!disposed && alive.current) { setBusy(false); inFlight.current = false; }
    }
    loadCaptcha({ region: config.region, prefix: config.prefix }).then(() => {
      if (disposed) return;
      initializedAt = Date.now();
      captchaWindow().initAliyunCaptcha?.({
        SceneId: config.scene_id, mode: "popup", element: "#phone-captcha-element",
        button: "#phone-captcha-button", slideStyle: { width: 320, height: 40 },
        getInstance: lifecycle.getInstance,
        onClose: (reason: string) => { if (reason === "userDismiss") release(); },
        onError: (errorInfo: { code?: string; msg?: string }) => {
          if (disposed) return;
          const detail = [errorInfo?.code, errorInfo?.msg].filter(Boolean).join("：");
          console.error("Aliyun captcha initialization failed", errorInfo);
          setError(`图形验证加载失败${detail ? `（${detail}）` : ""}，请稍后重试`);
          release();
        },
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
      lifecycle.dispose();
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

  return <Modal title={status.bound ? "更换手机号" : "绑定手机号"} eyebrow="PHONE VERIFICATION" onClose={onClose}>
    <form className="phone-binding-form modal-form" onSubmit={(event) => { event.preventDefault(); void confirm(); }}>
      <div className="phone-binding-intro">
        <span aria-hidden="true"><Smartphone size={20} /></span>
        <div>
          <strong>{status.bound ? "安全更换当前绑定号码" : "完善你的账号联系方式"}</strong>
          <p>{status.bound ? "新号码认证成功后才会替换当前号码，原号码在此期间保持有效。" : "完成图形验证和短信校验后即可绑定，不会改变现有密码登录方式。"}</p>
        </div>
      </div>
      <ol className="phone-binding-steps" aria-label="手机号绑定进度">
        <li className={challenge ? "is-complete" : "is-active"} aria-current={challenge ? undefined : "step"}>
          <span>{challenge ? <Check size={13} /> : "1"}</span>
          <div><strong>验证手机号</strong><small>图形验证并获取短信</small></div>
        </li>
        <li className={challenge ? "is-active" : ""} aria-current={challenge ? "step" : undefined}>
          <span>2</span>
          <div><strong>完成绑定</strong><small>填写短信验证码</small></div>
        </li>
      </ol>
      <section className="phone-binding-step-panel">
        <label className="field phone-number-field">
          <span>手机号</span>
          <div className="phone-number-input">
            <span>+86</span>
            <input type="tel" autoComplete="tel-national" value={phone} disabled={busy}
              placeholder="请输入 11 位手机号" maxLength={14}
              onChange={(event) => { setPhone(event.target.value); setChallenge(null); setCode(""); setError(""); }} />
          </div>
          <small className="field-hint">同一号码只能绑定一个账号，修改号码将重新开始验证。</small>
        </label>
        <div id="phone-captcha-element" className="phone-captcha-element" />
        <button id="phone-captcha-button" className="secondary-button phone-send-code-button" type="button"
          disabled={!sdkReady || busy || cooling > 0 || !validPhone(phone)}
          onClickCapture={() => { submittedPhone.current = phone.trim(); inFlight.current = true; setBusy(true); setError(""); }}>
          <Send size={15} />
          {cooling > 0 ? `${cooling} 秒后可重发` : !sdkReady ? "正在准备图形验证…" : challenge ? "重新发送短信验证码" : "发送短信验证码"}
        </button>
        {!sdkReady && error ? <button className="text-button phone-retry-button" type="button" disabled={busy}
          onClick={() => { setError(""); setCycle((value) => value + 1); }}>重试图形验证</button> : null}
      </section>
      {challenge ? <section className="phone-binding-step-panel phone-verification-panel">
        <InlineNotice tone={expired ? "warning" : "success"}>
          {expired ? "验证码已过期，请重新发送。" : "短信已发送，验证码 5 分钟内有效。"}
        </InlineNotice>
        <label className="field phone-sms-code-field">
          <span>短信验证码</span>
          <input inputMode="numeric" autoComplete="one-time-code" value={code} placeholder="请输入 6 位数字"
            maxLength={6} disabled={busy} onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))} />
        </label>
        {status.bound ? <label className="field">
          <span>当前登录密码</span>
          <input type="password" autoComplete="current-password" value={password} placeholder="用于确认本人操作"
            maxLength={256} disabled={busy} onChange={(event) => setPassword(event.target.value)} />
          <small className="field-hint">验证通过后才替换当前号码。</small>
        </label> : null}
      </section> : null}
      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
      <footer className="modal-actions">
        <button className="secondary-button" type="button" onClick={onClose}>取消</button>
        <button className="primary-button" type="submit"
          disabled={busy || !challenge || expired || code.length !== 6 || (status.bound && !password)}>
          {busy ? "正在验证…" : status.bound ? "确认更换" : "确认绑定"}
        </button>
      </footer>
    </form>
  </Modal>;
}
