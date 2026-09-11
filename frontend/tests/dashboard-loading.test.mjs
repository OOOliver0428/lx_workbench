import assert from "node:assert/strict";
import test from "node:test";
import { createLatestRequest, readManagementScope, saveManagementScope } from "../app/dashboard-loading.ts";

test("keeps only the newest department response and ignores stale errors", async () => {
  const gate = createLatestRequest();
  let resolveOld;
  const old = gate.run(() => new Promise(resolve => { resolveOld = resolve; }));
  assert.deepEqual(await gate.run(async () => ({ week: "2026-09-07", department: "B" })),
                   { week: "2026-09-07", department: "B" });
  resolveOld({ week: "2026-09-14", department: "A" });
  assert.equal(await old, undefined);
  let rejectOld;
  const failed = gate.run(() => new Promise((_, reject) => { rejectOld = reject; }));
  await gate.run(async () => "latest");
  rejectOld(new Error("obsolete failure"));
  assert.equal(await failed, undefined);
  await assert.rejects(gate.run(async () => { throw new Error("current failure"); }), /current failure/);
});

test("ignores pending responses after unmount", async () => {
  const gate = createLatestRequest();
  let resolve;
  const pending = gate.run(() => new Promise(done => { resolve = done; }));
  gate.cancel();
  resolve("old account data");
  assert.equal(await pending, undefined);
});

test("remembers scopes per account and tolerates unavailable storage", () => {
  const values = new Map();
  globalThis.window = { localStorage: { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) } };
  saveManagementScope("alice", "department", "A");
  saveManagementScope("bob", "department", "B");
  assert.equal(readManagementScope("alice").departmentId, "A");
  assert.equal(readManagementScope("bob").departmentId, "B");
  values.set("workMgmt.scope:alice", "bad json");
  assert.equal(readManagementScope("alice").scopeType, "");
  delete globalThis.window;
  assert.equal(readManagementScope("alice").departmentId, "");
});
