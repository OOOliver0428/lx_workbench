import assert from "node:assert/strict";
import test from "node:test";
import {
  ACTION_LABELS,
  ENTITY_TYPE_LABELS,
  SYSTEM_ACTOR_FILTER,
  collectAuditActions,
  collectAuditActors,
  filterAuditEvents,
  formatAuditAction,
  formatAuditActor,
  formatAuditEntity,
  hasActiveAuditFilters,
} from "../app/audit-labels.ts";

let sequence = 0;

function auditEvent(overrides = {}) {
  sequence += 1;
  return {
    id: `event-${sequence}`,
    request_id: null,
    actor_id: null,
    actor_name: null,
    action: "task.update",
    entity_type: "task",
    entity_id: null,
    before_data: null,
    after_data: null,
    result: "success",
    detail: null,
    client_ip: null,
    created_at: new Date(2026, 8, 22, 10, 0, 0).toISOString(),
    ...overrides,
  };
}

function localTime(hour, minute = 0, second = 0) {
  return new Date(2026, 8, 22, hour, minute, second).toISOString();
}

test("action labels cover every audited action and unknown actions fall back", () => {
  assert.equal(Object.keys(ACTION_LABELS).length, 59);
  for (const key of Object.keys(ACTION_LABELS)) {
    assert.match(key, /^[a-z][a-z0-9_.]*$/);
  }
  assert.equal(formatAuditAction("work_record.update"), "更新工作记录");
  assert.equal(formatAuditAction("auth.login"), "登录系统");
  assert.equal(formatAuditAction("ai.chat.clear"), "清空 AI 对话记录");
  assert.equal(formatAuditAction("team_weekly_summary.regenerate"), "重新生成团队周报汇总");
  assert.equal(formatAuditAction("some.unknown.action"), "some.unknown.action");
});

test("entity labels format type name with short id and degrade gracefully", () => {
  assert.equal(Object.keys(ENTITY_TYPE_LABELS).length, 17);
  assert.equal(
    formatAuditEntity("work_record", "a1b2c3d4-e5f6-7890-abcd-ef1234567890"),
    "工作记录 · a1b2c3d4",
  );
  assert.equal(formatAuditEntity("weekly_report", "12345678abcd"), "周报 · 12345678");
  assert.equal(formatAuditEntity("ai", null), "AI 助手");
  assert.equal(formatAuditEntity("ai_configuration", null), "大模型配置");
  assert.equal(formatAuditEntity("mystery_type", "abcdef123456"), "mystery_type · abcdef12");
});

test("actor display falls back to 系统 for system events", () => {
  assert.equal(formatAuditActor("user-1", "成员甲"), "成员甲");
  assert.equal(formatAuditActor(null, null), "系统");
  assert.equal(formatAuditActor("user-gone", null), "未知用户");
});

test("collectAuditActors lists distinct actors with 系统 first", () => {
  const events = [
    auditEvent({ actor_id: "u2", actor_name: "成员乙" }),
    auditEvent({ actor_id: "u1", actor_name: "成员甲" }),
    auditEvent({ actor_id: "u2", actor_name: "成员乙" }),
    auditEvent(),
  ];
  assert.deepEqual(collectAuditActors(events), [
    { value: SYSTEM_ACTOR_FILTER, label: "系统" },
    { value: "u1", label: "成员甲" },
    { value: "u2", label: "成员乙" },
  ]);
  assert.deepEqual(collectAuditActors([auditEvent({ actor_id: "u1", actor_name: "成员甲" })]), [
    { value: "u1", label: "成员甲" },
  ]);
});

test("collectAuditActions lists distinct actions with Chinese labels", () => {
  const events = [
    auditEvent({ action: "work_record.delete" }),
    auditEvent({ action: "auth.login" }),
    auditEvent({ action: "work_record.delete" }),
    auditEvent({ action: "plugin.future" }),
  ];
  const options = collectAuditActions(events);
  assert.deepEqual(
    options.map((option) => option.value).sort(),
    ["auth.login", "plugin.future", "work_record.delete"],
  );
  const byValue = Object.fromEntries(options.map((option) => [option.value, option.label]));
  assert.equal(byValue["auth.login"], "登录系统");
  assert.equal(byValue["work_record.delete"], "删除工作记录");
  assert.equal(byValue["plugin.future"], "plugin.future");
});

test("filterAuditEvents matches actor including the 系统 sentinel", () => {
  const events = [
    auditEvent({ actor_id: "u1", actor_name: "成员甲" }),
    auditEvent({ actor_id: "u2", actor_name: "成员乙" }),
    auditEvent(),
  ];
  assert.deepEqual(
    filterAuditEvents(events, { actorId: "u1" }).map((event) => event.actor_id),
    ["u1"],
  );
  assert.deepEqual(
    filterAuditEvents(events, { actorId: SYSTEM_ACTOR_FILTER }).map((event) => event.actor_id),
    [null],
  );
  assert.equal(filterAuditEvents(events, {}).length, 3);
});

test("filterAuditEvents matches action and time range with inclusive bounds", () => {
  const early = auditEvent({ action: "auth.login", created_at: localTime(9, 15) });
  const onTheMinute = auditEvent({
    action: "task.update",
    created_at: localTime(10, 30, 45),
  });
  const late = auditEvent({ action: "task.delete", created_at: localTime(11, 5) });
  const events = [early, onTheMinute, late];

  assert.deepEqual(filterAuditEvents(events, { action: "task.update" }), [onTheMinute]);
  assert.deepEqual(
    filterAuditEvents(events, { from: "2026-09-22T10:00" }),
    [onTheMinute, late],
  );
  // A minute-precision 截止 covers the whole minute (10:30:59 inclusive).
  assert.deepEqual(
    filterAuditEvents(events, { to: "2026-09-22T10:30" }),
    [early, onTheMinute],
  );
  assert.deepEqual(
    filterAuditEvents(events, { from: "2026-09-22T09:00", to: "2026-09-22T10:30" }),
    [early, onTheMinute],
  );
  assert.deepEqual(filterAuditEvents(events, { from: "2026-09-22T10:31" }), [late]);
  // Unparseable input is ignored instead of dropping everything.
  assert.equal(filterAuditEvents(events, { from: "not-a-time", to: "??" }).length, 3);
});

test("filterAuditEvents combines actor, action and time range", () => {
  const target = auditEvent({
    actor_id: "u1",
    actor_name: "成员甲",
    action: "work_record.update",
    created_at: localTime(10, 0),
  });
  const events = [
    target,
    auditEvent({ actor_id: "u1", actor_name: "成员甲", action: "work_record.delete", created_at: localTime(10, 0) }),
    auditEvent({ actor_id: "u2", actor_name: "成员乙", action: "work_record.update", created_at: localTime(10, 0) }),
    auditEvent({ actor_id: "u1", actor_name: "成员甲", action: "work_record.update", created_at: localTime(12, 0) }),
  ];
  assert.deepEqual(
    filterAuditEvents(events, {
      actorId: "u1",
      action: "work_record.update",
      from: "2026-09-22T09:00",
      to: "2026-09-22T11:00",
    }),
    [target],
  );
});

test("hasActiveAuditFilters reflects whether any filter is set", () => {
  assert.equal(hasActiveAuditFilters({}), false);
  assert.equal(hasActiveAuditFilters({ actorId: "", action: "", from: "", to: "" }), false);
  assert.equal(hasActiveAuditFilters({ actorId: SYSTEM_ACTOR_FILTER }), true);
  assert.equal(hasActiveAuditFilters({ action: "auth.login" }), true);
  assert.equal(hasActiveAuditFilters({ from: "2026-09-22T00:00" }), true);
  assert.equal(hasActiveAuditFilters({ to: "2026-09-22T23:59" }), true);
});
