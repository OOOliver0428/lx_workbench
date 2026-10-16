import assert from "node:assert/strict";
import test from "node:test";
import {
  avatarSource, avatarCropGeometry, validateAvatarFile, avatarRequestLimit,
  MAX_AVATAR_FILE_BYTES, MAX_AVATAR_REQUEST_BYTES,
} from "../app/avatar-upload.ts";

test("custom avatars use authenticated system URLs and presets remain local", () => {
  assert.equal(avatarSource("custom-" + "a".repeat(32)), "/api/v1/avatars/" + "a".repeat(32));
  assert.equal(avatarSource("clay-soft-01"), "/avatars/clay-soft-01.webp");
  assert.equal(avatarSource(null), "");
  for (const key of ["../../secret", "https://example.com/image", "custom-invalid", "custom-" + "A".repeat(32)]) {
    assert.equal(avatarSource(key), "");
  }
});

test("crop matches centered, zoomed, and edge-aligned square geometry", () => {
  assert.deepEqual(avatarCropGeometry(1200, 800, 1, 50, 50), {
    left: 200, top: 0, edge: 800, crop: { x: 1 / 6, y: 0, size: 1 },
  });
  assert.deepEqual(avatarCropGeometry(600, 1200, 2, 100, 100), {
    left: 300, top: 900, edge: 300, crop: { x: 0.5, y: 0.75, size: 0.5 },
  });
  for (const [width, height] of [[997, 601], [601, 997], [1, 1]]) {
    const { left, top, edge, crop } = avatarCropGeometry(width, height, 4, 100, 100);
    assert.ok(left >= 0 && top >= 0 && left + edge <= width && top + edge <= height);
    assert.ok(crop.x >= 0 && crop.y >= 0 && crop.size > 0);
  }
  assert.throws(() => avatarCropGeometry(0, 50, 1, 50, 50), RangeError);
  assert.throws(() => avatarCropGeometry(50, 50, NaN, 50, 50), RangeError);
});

test("file selection rejects empty, oversized and unsupported images", () => {
  assert.equal(validateAvatarFile({ size: MAX_AVATAR_FILE_BYTES, type: "image/png" }), "");
  assert.match(validateAvatarFile({ size: 0, type: "image/png" }), /为空/);
  assert.match(validateAvatarFile({ size: MAX_AVATAR_FILE_BYTES + 1, type: "image/webp" }), /5 MiB/);
  assert.match(validateAvatarFile({ size: 500, type: "image/svg+xml" }), /JPG/);
});

test("only exact upload path gets the larger multipart allowance", () => {
  assert.equal(avatarRequestLimit("/api/v1/profile/avatar/upload", 262144), MAX_AVATAR_REQUEST_BYTES);
  for (const path of ["/api/v1/profile/avatar", "/api/v1/profile/avatar/upload/", "/api/v1/profile/avatar/upload-extra", "/api/v1/users"]) {
    assert.equal(avatarRequestLimit(path, 262144), 262144);
  }
});

test("multipart API client leaves content type to the browser and sends CSRF", async () => {
  const { api, setCsrfToken } = await import("../app/api.ts");
  const previousFetch = globalThis.fetch;
  let captured;
  globalThis.fetch = async (url, init) => {
    captured = { url, init };
    return Response.json({ avatar_key: "custom-" + "b".repeat(32), revision: 4 });
  };
  try {
    setCsrfToken("test-csrf");
    const file = new File(["test-image"], "avatar.png", { type: "image/png" });
    await api.profile.uploadAvatar(3, file, { x: 0, y: 0, size: 1 });
    assert.equal(captured.url, "/api/v1/profile/avatar/upload");
    assert.equal(captured.init.headers.get("content-type"), null);
    assert.equal(captured.init.headers.get("x-csrf-token"), "test-csrf");
    assert.equal(captured.init.credentials, "include");
    assert.equal(captured.init.body.get("revision"), "3");
    assert.equal(captured.init.body.get("file").name, "avatar.png");
    assert.deepEqual(JSON.parse(captured.init.body.get("crop")), { x: 0, y: 0, size: 1 });
  } finally {
    globalThis.fetch = previousFetch;
    setCsrfToken("");
  }
});

test("proxy forwards avatar multipart only within its dedicated hard limit", async () => {
  const previousFetch = globalThis.fetch;
  const previousLimit = process.env.MVP_MAX_REQUEST_BODY_BYTES;
  process.env.MVP_MAX_REQUEST_BODY_BYTES = "16";
  let calls = 0;
  let forwarded;
  globalThis.fetch = async (_url, init) => {
    calls += 1;
    forwarded = init;
    return Response.json({ revision: 5 });
  };
  const { POST } = await import("../app/api/[...path]/route.ts");
  const context = { params: Promise.resolve({ path: ["v1", "profile", "avatar", "upload"] }) };
  try {
    const form = new FormData();
    form.append("file", new File([new Uint8Array(300000)], "avatar.png", { type: "image/png" }));
    const response = await POST(new Request("http://localhost/api/v1/profile/avatar/upload", {
      method: "POST", headers: { cookie: "mvp_session=test", "x-csrf-token": "csrf" }, body: form,
    }), context);
    assert.equal(response.status, 200);
    assert.equal(calls, 1);
    assert.match(forwarded.headers.get("content-type"), /^multipart\/form-data; boundary=/);
    assert.equal(forwarded.headers.get("cookie"), "mvp_session=test");
    assert.ok(forwarded.body.byteLength > 300000);
    const oversized = await POST(new Request("http://localhost/api/v1/profile/avatar/upload", {
      method: "POST", body: new Uint8Array(MAX_AVATAR_REQUEST_BYTES + 1),
    }), context);
    assert.equal(oversized.status, 413);
    assert.equal((await oversized.json()).details.max_bytes, MAX_AVATAR_REQUEST_BYTES);
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = previousFetch;
    if (previousLimit === undefined) delete process.env.MVP_MAX_REQUEST_BODY_BYTES;
    else process.env.MVP_MAX_REQUEST_BODY_BYTES = previousLimit;
  }
});
