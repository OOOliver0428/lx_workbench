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
