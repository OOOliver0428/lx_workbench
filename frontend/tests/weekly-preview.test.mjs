import assert from "node:assert/strict";
import test from "node:test";
import { createWeeklyPreviewState, weeklyPreviewReducer } from "../app/weekly-preview.ts";

function generate(state, id, content, guidance = "") {
  return weeklyPreviewReducer(state, {
    type: "generated", id, content, guidance, createdAt: "10:00:00",
  });
}

function restore(state, versionId, id = "switch") {
  return weeklyPreviewReducer(state, { type: "restore", id, versionId, createdAt: "10:01:00" });
}

function edit(state, content) {
  return weeklyPreviewReducer(state, { type: "edit", content });
}

test("guided regeneration keeps every AI draft available for repeated rollback", () => {
  let state = generate(createWeeklyPreviewState(), "v1", "原始周报");
  state = generate(state, "v2", "突出风险的周报", "突出风险");
  state = generate(state, "v3", "精简周报", "请精简");
  assert.deepEqual(state.versions.map(v => [v.id, v.generation]), [["v3", 3], ["v2", 2], ["v1", 1]]);
  const versions = state.versions;
  for (const [id, content] of [["v1", "原始周报"], ["v3", "精简周报"], ["v2", "突出风险的周报"]]) {
    state = restore(state, id);
    assert.equal(state.content, content);
    assert.equal(state.activeVersionId, id);
    assert.equal(state.versions, versions);
  }
  assert.equal(state.versions.find(v => v.id === "v2").guidance, "突出风险");
});

test("regeneration snapshots manual edits without changing the original AI version", () => {
  let state = generate(createWeeklyPreviewState(), "v1", "AI 原文", "风险优先");
  state = edit(state, "我补充的事实");
  const before = structuredClone(state);
  state = generate(state, "v2", "新的 AI 版本", "语气简洁");
  const snapshot = state.versions.find(v => v.kind === "edited");
  assert.equal(snapshot.content, "我补充的事实");
  assert.equal(snapshot.guidance, "风险优先");
  assert.equal(state.versions.find(v => v.id === "v1").content, "AI 原文");
  assert.deepEqual(before.versions.map(v => v.content), ["AI 原文"]);
  assert.equal(restore(state, snapshot.id).content, "我补充的事实");
});

test("switching versions snapshots edits even when returning to the active AI original", () => {
  let state = generate(createWeeklyPreviewState(), "v1", "AI 原文");
  state = edit(state, "手动编辑");
  state = restore(state, "v1");
  assert.equal(state.content, "AI 原文");
  assert.equal(state.versions.length, 2);
  const edited = state.versions.find(v => v.kind === "edited");
  state = restore(state, edited.id, "switch-back");
  assert.equal(state.content, "手动编辑");
  assert.equal(state.versions.length, 2);
});

test("the draft loaded on opening remains recoverable after editing and regeneration", () => {
  let state = createWeeklyPreviewState("已有数据库草稿");
  state = edit(state, "已有草稿的手动修改");
  state = generate(state, "v1", "AI 新稿");
  assert.equal(restore(state, "saved-initial").content, "已有数据库草稿");
  const edited = state.versions.find(v => v.kind === "edited");
  assert.equal(restore(state, edited.id).content, "已有草稿的手动修改");
  assert.equal(state.versions[0].generation, 1);
});

test("saving a draft retains session history and subsequent AI numbering", () => {
  let state = generate(createWeeklyPreviewState(), "v1", "第一版");
  state = edit(state, "编辑并保存");
  state = weeklyPreviewReducer(state, { type: "saved", content: "编辑并保存" });
  state = generate(state, "v2", "第二版");
  assert.equal(state.versions[0].generation, 2);
  assert.equal(restore(state, "v1").content, "第一版");
  assert.ok(state.versions.some(v => v.content === "编辑并保存"));
});

test("reopening starts a new session with only the persisted draft", () => {
  const previous = generate(createWeeklyPreviewState(), "v1", "未保存预览");
  assert.equal(previous.versions.length, 1);
  assert.deepEqual(createWeeklyPreviewState(), { content: "", versions: [], activeVersionId: "" });
  const reopened = createWeeklyPreviewState("已保存的正文");
  assert.deepEqual(reopened.versions.map(v => v.kind), ["saved"]);
  assert.equal(restore(reopened, "v1"), reopened);
});
