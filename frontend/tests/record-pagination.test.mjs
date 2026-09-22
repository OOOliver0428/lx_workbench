import assert from "node:assert/strict";
import test from "node:test";
import { recordListParams } from "../app/record-pagination.ts";

test("later pages retain week and source filters", () => {
  for (const source of [
    { projectId: "project-a", departmentWorkId: "", unassignedOnly: false },
    { projectId: "", departmentWorkId: "department-work-a", unassignedOnly: false },
    { projectId: "", departmentWorkId: "", unassignedOnly: true },
  ]) {
    const filters = { ...source, currentWeekOnly: true };
    const first = recordListParams(filters);
    const next = recordListParams(filters, { work_date: "2026-09-22", id: "record-50" });
    assert.equal(next.get("before_date"), "2026-09-22");
    assert.equal(next.get("before_id"), "record-50");
    assert.equal(next.get("current_week_only"), "true");
    for (const [key, value] of first) assert.equal(next.get(key), value);
    assert.equal(first.has("before_id"), false);
  }
});

test("changing filters starts without a cursor or stale week restriction", () => {
  const next = recordListParams({
    projectId: "new-project", departmentWorkId: "", unassignedOnly: false,
    currentWeekOnly: false,
  });
  assert.equal(next.get("project_id"), "new-project");
  assert.equal(next.has("before_id"), false);
  assert.equal(next.has("current_week_only"), false);
});
