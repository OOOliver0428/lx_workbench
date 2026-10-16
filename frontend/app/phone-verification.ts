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

export interface CaptchaInstance {
  hide?: () => void;
  destroyCaptcha?: () => void;
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
