import assert from "node:assert/strict";
import test from "node:test";
import nextConfig from "../next.config.ts";
import {
  loadCaptcha, validPhone, remainingSeconds, CAPTCHA_SCRIPT_URL, createCaptchaLifecycle, captchaWarmupRemaining,
} from "../app/phone-verification.ts";

test("captcha warmup counts initialization time instead of adding a second delay", () => {
  assert.equal(captchaWarmupRemaining(1000, 1000), 2100);
  assert.equal(captchaWarmupRemaining(1000, 2500), 600);
  assert.equal(captchaWarmupRemaining(1000, 3100), 0);
  assert.equal(captchaWarmupRemaining(1000, 12000), 0);
});

test("captcha resource policy permits SDK styles and device checks without opening arbitrary origins", async () => {
  const rules = await nextConfig.headers();
  const csp = rules.find((rule) => rule.source === "/(.*)").headers
    .find((header) => header.key === "Content-Security-Policy").value;
  const directives = new Map(csp.split(";").map((part) => {
    const [name, ...sources] = part.trim().split(/\s+/);
    return [name, sources];
  }));
  const styles = directives.get("style-src");
  for (const host of ["g", "x"]) {
    assert.ok(styles.includes(`https://${host}.alicdn.com/captcha-frontend/`));
  }
  const connections = directives.get("connect-src");
  assert.ok(connections.includes("https://cloudauth-device-dualstack.cn-shanghai.aliyuncs.com"));
  assert.ok(connections.includes("data:"));
  for (const sources of [styles, connections]) {
    assert.ok(!sources.includes("*"));
    assert.ok(!sources.includes("https:"));
  }
  assert.deepEqual(directives.get("object-src"), ["'none'"]);
  assert.deepEqual(directives.get("frame-ancestors"), ["'none'"]);
});

test("SDK destruction can call getInstance without a value or reenter with the old instance", () => {
  let ready = 0, destroyed = 0;
  const lifecycle = createCaptchaLifecycle(() => { ready++; });
  const instance = { destroyCaptcha() {
    destroyed++;
    lifecycle.getInstance(undefined);
    lifecycle.getInstance(null);
    lifecycle.getInstance(instance);
  } };
  lifecycle.getInstance(instance);
  lifecycle.dispose();
  lifecycle.dispose();
  assert.equal(ready, 1);
  assert.equal(destroyed, 1);
});

test("late initialization after closing is destroyed without affecting a reopened dialog", () => {
  let oldReady = 0, newReady = 0, destroyed = 0;
  const old = createCaptchaLifecycle(() => { oldReady++; });
  old.dispose();
  const reopened = createCaptchaLifecycle(() => { newReady++; });
  reopened.getInstance({});
  old.getInstance({ destroyCaptcha() { destroyed++; old.getInstance(); } });
  assert.equal(oldReady, 0);
  assert.equal(newReady, 1);
  assert.equal(destroyed, 1);
  reopened.dispose();
});

test("only normalized mainland mobile formats are accepted", () => {
  assert.equal(validPhone("13800138000"), true);
  assert.equal(validPhone("+8613800138000"), true);
  for (const value of ["+14155552671", "1380013800", "13800138000x", "０１３８００１３８０００"]) {
    assert.equal(validPhone(value), false);
  }
});

test("cooldown derives from deadline and never becomes negative", () => {
  assert.equal(remainingSeconds(10000, 9001), 1);
  assert.equal(remainingSeconds(10000, 10000), 0);
  assert.equal(remainingSeconds(10000, 99000), 0);
});

test("SDK is lazy, deduplicated, retries failed loads, and guards changed configuration", async () => {
  const scripts = [];
  let removed = 0;
  globalThis.window = { setTimeout, clearTimeout };
  globalThis.document = {
    createElement: () => ({ remove() { removed += 1; } }),
    head: { appendChild(script) { scripts.push(script); } },
  };
  try {
    assert.equal(scripts.length, 0);
    const config = { region: "cn", prefix: "test-prefix" };
    const failed = loadCaptcha(config);
    assert.equal(loadCaptcha(config), failed);
    assert.equal(scripts[0].src, CAPTCHA_SCRIPT_URL);
    scripts[0].onerror();
    await assert.rejects(failed, /加载失败/);
    assert.equal(removed, 1);
    const loaded = loadCaptcha(config);
    assert.equal(scripts.length, 2);
    window.initAliyunCaptcha = () => {};
    scripts[1].onload();
    await loaded;
    await loadCaptcha(config);
    assert.equal(scripts.length, 2);
    await assert.rejects(loadCaptcha({ ...config, prefix: "changed" }), /刷新页面/);
  } finally {
    delete globalThis.window;
    delete globalThis.document;
  }
});
