import assert from "node:assert/strict";
import test from "node:test";
import {
  loadCaptcha, validPhone, remainingSeconds, CAPTCHA_SCRIPT_URL,
} from "../app/phone-verification.ts";

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
