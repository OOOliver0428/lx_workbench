export interface PhoneStatus {
  availability: "ready" | "disabled" | "unavailable";
  bound: boolean;
  phone_masked: string | null;
  verified_at: string | null;
  revision: number;
  retry_after: number;
  captcha: { region: string; prefix: string; scene_id: string } | null;
}

export interface PhoneChallenge {
  challenge_id: string;
  expires_at: string;
  retry_after: number;
}

export function validPhone(value: string): boolean {
  return /^(?:\+86)?1[3-9][0-9]{9}$/.test(value.trim());
}

export function remainingSeconds(deadline: number, now = Date.now()): number {
  return Math.max(0, Math.ceil((deadline - now) / 1000));
}

export function captchaWarmupRemaining(startedAt: number, now = Date.now()): number {
  return Math.max(0, 2100 - Math.max(0, now - startedAt));
}

export interface CaptchaInstance {
  hide?: () => void;
  destroyCaptcha?: () => void;
}

export function createCaptchaLifecycle(onReady: (value: CaptchaInstance) => void) {
  let disposed = false;
  let current: CaptchaInstance | null = null;
  const destroyed = new WeakSet<CaptchaInstance>();
  function destroy(value: CaptchaInstance) {
    if (destroyed.has(value)) return;
    destroyed.add(value);
    value.hide?.();
    value.destroyCaptcha?.();
  }
  return {
    getInstance(value?: CaptchaInstance | null) {
      // The SDK calls back without an instance when destroyCaptcha completes.
      if (!value) return;
      if (disposed) { destroy(value); return; }
      current = value;
      onReady(value);
    },
    dispose() {
      disposed = true;
      const value = current;
      current = null;
      if (value) destroy(value);
    },
  };
}

type CaptchaWindow = Window & {
  AliyunCaptchaConfig?: { region: string; prefix: string };
  initAliyunCaptcha?: (options: Record<string, unknown>) => void;
};

let scriptPromise: Promise<void> | null = null;
let loadedConfig = "";
export const CAPTCHA_SCRIPT_URL = "https://o.alicdn.com/captcha-frontend/aliyunCaptcha/AliyunCaptcha.js";

export function captchaWindow(): CaptchaWindow {
  return window as CaptchaWindow;
}

export function loadCaptcha(config: { region: string; prefix: string }): Promise<void> {
  const identity = JSON.stringify(config);
  if (scriptPromise) {
    if (loadedConfig !== identity) {
      return Promise.reject(new Error("验证码配置已更新，请刷新页面"));
    }
    return scriptPromise;
  }
  loadedConfig = identity;
  captchaWindow().AliyunCaptchaConfig = config;
  scriptPromise = new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = CAPTCHA_SCRIPT_URL;
    script.async = true;
    const timer = window.setTimeout(() => fail(), 12000);
    function fail() {
      window.clearTimeout(timer);
      script.onload = script.onerror = null;
      script.remove();
      scriptPromise = null;
      loadedConfig = "";
      reject(new Error("图形验证加载失败，请检查网络后重试"));
    }
    script.onload = () => {
      window.clearTimeout(timer);
      if (!captchaWindow().initAliyunCaptcha) { fail(); return; }
      resolve();
    };
    script.onerror = fail;
    document.head.appendChild(script);
  });
  return scriptPromise;
}
