import type { ProjectSummary, Task, User, UserRole } from "./types";

const PRIVILEGED_ROLES: ReadonlySet<UserRole> = new Set([
  "team_leader",
  "system_admin",
  "super_admin",
]);

export function canManageProjectObject(
  hasManagePermission: boolean,
  currentUser: User,
  project: Pick<ProjectSummary, "owner_id">,
) {
  return (
    hasManagePermission &&
    (PRIVILEGED_ROLES.has(currentUser.role) ||
      project.owner_id === currentUser.id)
  );
}

/**
 * 任务对象级管理权限：具备 manage 权限，且为特权角色、任务负责人或来源负责人。
 * 第 4 参 projectOwnerId 语义已泛化为「来源负责人」：项目来源传项目 owner_id，
 * 部门工作来源传部门工作的 owner_id。
 */
export function canManageTaskObject(
  hasManagePermission: boolean,
  currentUser: User,
  task: Pick<Task, "owner_id">,
  projectOwnerId: string | undefined,
) {
  return (
    hasManagePermission &&
    (PRIVILEGED_ROLES.has(currentUser.role) ||
      task.owner_id === currentUser.id ||
      projectOwnerId === currentUser.id)
  );
}
