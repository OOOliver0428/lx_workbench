export const RECORD_PAGE_SIZE = 50;

export function recordListParams(
  filters: {
    projectId: string;
    departmentWorkId: string;
    unassignedOnly: boolean;
    currentWeekOnly: boolean;
  },
  cursor?: { work_date: string; id: string },
) {
  const params = new URLSearchParams({ limit: String(RECORD_PAGE_SIZE) });
  if (filters.projectId) params.set("project_id", filters.projectId);
  if (filters.departmentWorkId) params.set("department_work_id", filters.departmentWorkId);
  if (filters.unassignedOnly) params.set("unassigned_only", "true");
  if (filters.currentWeekOnly) params.set("current_week_only", "true");
  if (cursor) {
    params.set("before_date", cursor.work_date);
    params.set("before_id", cursor.id);
  }
  return params;
}
