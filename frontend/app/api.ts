import type {
  AIChatResult,
  AIConfiguration,
  AIConfigurationTestResult,
  AIProviderOption,
  AIStatus,
  ApiErrorBody,
  AuditEvent,
  AuthContext,
  AvatarOption,
  Department,
  DepartmentWork,
  DepartmentWorkStatus,
  DepartmentWorkVisibility,
  DuplicateCandidate,
  Opportunity,
  Project,
  ProjectMergePreview,
  ProjectMergeResult,
  ProjectSummary,
  ProjectTag,
  Task,
  TaskProgressHistory,
  User,
  UserCandidate,
  CurrentWeeklyReport,
  Dashboard,
  TeamWeeklySummary,
  PermissionDefinition,
  PermissionKey,
  WeeklyReport,
  WorkRecord,
  WorkRecordQuickCreateResult,
  UserPermissions,
  TimeBlock,
} from "./types";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(
  /\/+$/,
  "",
);

let csrfToken = "";
let sessionInvalidatedHandler:
  | ((message: string) => void)
  | null = null;

const SESSION_PROBE_PATHS = new Set([
  "/api/v1/auth/login",
  "/api/v1/auth/me",
  "/api/v1/auth/logout",
]);

type AuthContextResponse = Omit<AuthContext, "permissions"> & {
  permissions?: PermissionKey[];
};

function normalizeAuthContext(context: AuthContextResponse): AuthContext {
  return {
    ...context,
    permissions: Array.isArray(context.permissions) ? context.permissions : [],
  };
}

export class ApiClientError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown> | null;
  requestId: string | null;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message || "请求失败");
    this.name = "ApiClientError";
    this.status = status;
    this.code = body.code || "UNKNOWN_ERROR";
    this.details = body.details;
    this.requestId = body.request_id;
  }
}

export function apiErrorMessage(caught: unknown, fallback: string) {
  if (!(caught instanceof ApiClientError)) return fallback;
  const retryHint =
    caught.status === 409
      ? " 数据已被其他人更新，请刷新最新版本后重试。"
      : "";
  const requestHint = caught.requestId
    ? `（请求编号：${caught.requestId}）`
    : "";
  return `${caught.message}${retryHint}${requestHint}`;
}

export function setCsrfToken(value: string) {
  csrfToken = value;
}

export function setSessionInvalidatedHandler(
  handler: ((message: string) => void) | null,
) {
  sessionInvalidatedHandler = handler;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (response.status === 204) {
    return undefined as T;
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new ApiClientError(response.status, {
      code: body?.code ?? "HTTP_ERROR",
      message: body?.message ?? `请求失败（${response.status}）`,
      request_id: body?.request_id ?? null,
      details: body?.details ?? null,
    });
    if (response.status === 401 && !SESSION_PROBE_PATHS.has(path)) {
      setCsrfToken("");
      sessionInvalidatedHandler?.(error.message);
    }
    throw error;
  }
  return body as T;
}

export const api = {
  auth: {
    login: async (loginIdentifier: string, password: string) =>
      normalizeAuthContext(
        await request<AuthContextResponse>("/api/v1/auth/login", {
          method: "POST",
          body: JSON.stringify({ login_name: loginIdentifier, password }),
        }),
      ),
    me: async () =>
      normalizeAuthContext(
        await request<AuthContextResponse>("/api/v1/auth/me"),
      ),
    logout: () => request<void>("/api/v1/auth/logout", { method: "POST" }),
    changePassword: (currentPassword: string, newPassword: string) =>
      request<void>("/api/v1/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      }),
  },
  users: {
    list: (includeInactive = false) =>
      request<User[]>(
        `/api/v1/users${includeInactive ? "?include_inactive=true" : ""}`,
      ),
    candidates: () =>
      request<UserCandidate[]>("/api/v1/users/candidates"),
    permissionCatalog: () =>
      request<PermissionDefinition[]>("/api/v1/users/permissions/catalog"),
    permissions: (id: string) =>
      request<UserPermissions>(`/api/v1/users/${id}/permissions`),
    updatePermissions: (
      id: string,
      revision: number,
      permissions: PermissionKey[],
    ) =>
      request<UserPermissions>(`/api/v1/users/${id}/permissions`, {
        method: "PUT",
        body: JSON.stringify({ revision, permissions }),
      }),
    create: (payload: {
      display_name: string;
      password: string;
      role: string;
      primary_department_id?: string | null;
    }) =>
      request<User>("/api/v1/users", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    updateLeader: (id: string, revision: number, leaderId: string | null) =>
      request<User>(`/api/v1/users/${id}/leader`, {
        method: "PATCH",
        body: JSON.stringify({ revision, leader_id: leaderId }),
      }),
    update: (
      id: string,
      payload: {
        revision: number;
        display_name: string;
        role: string;
        leader_id: string | null;
        primary_department_id?: string | null;
      },
    ) =>
      request<User>(`/api/v1/users/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
  },
  departments: {
    list: (includeInactive = false, query?: string) => {
      const params = new URLSearchParams();
      if (includeInactive) params.set("include_inactive", "true");
      if (query?.trim()) params.set("q", query.trim());
      return request<Department[]>(
        `/api/v1/departments${params.size ? `?${params}` : ""}`,
      );
    },
    create: (payload: { name: string; leader_id?: string | null }) =>
      request<Department>("/api/v1/departments", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    update: (
      id: string,
      payload: {
        revision: number;
        name?: string;
        leader_id?: string | null;
        is_active?: boolean;
      },
    ) =>
      request<Department>(`/api/v1/departments/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    remove: (id: string, revision: number, reason?: string | null) =>
      request<void>(`/api/v1/departments/${id}`, {
        method: "DELETE",
        body: JSON.stringify({ revision, reason: reason || null }),
      }),
  },
  departmentWorks: {
    list: (params?: URLSearchParams) =>
      request<DepartmentWork[]>(
        `/api/v1/department-works${params?.size ? `?${params}` : ""}`,
      ),
    get: (id: string) =>
      request<DepartmentWork>(`/api/v1/department-works/${id}`),
    create: (payload: {
      name: string;
      description?: string | null;
      department_id?: string | null;
      owner_id?: string | null;
      visibility?: DepartmentWorkVisibility;
    }) =>
      request<DepartmentWork>("/api/v1/department-works", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    update: (
      id: string,
      payload: {
        revision: number;
        name?: string;
        description?: string | null;
        owner_id?: string | null;
        visibility?: DepartmentWorkVisibility;
      },
    ) =>
      request<DepartmentWork>(`/api/v1/department-works/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    transition: (id: string, revision: number, status: DepartmentWorkStatus) =>
      request<DepartmentWork>(`/api/v1/department-works/${id}/transition`, {
        method: "POST",
        body: JSON.stringify({ revision, status }),
      }),
    remove: (id: string, revision: number, reason?: string | null) =>
      request<void>(`/api/v1/department-works/${id}`, {
        method: "DELETE",
        body: JSON.stringify({ revision, reason: reason || null }),
      }),
  },
  audit: {
    list: () => request<AuditEvent[]>("/api/v1/audit-events?limit=100"),
  },
  profile: {
    avatars: () => request<AvatarOption[]>("/api/v1/profile/avatars"),
    updateAvatar: (revision: number, avatarKey: string | null) =>
      request<User>("/api/v1/profile/avatar", {
        method: "PATCH",
        body: JSON.stringify({ revision, avatar_key: avatarKey }),
      }),
  },
  tags: {
    list: (includeInactive = false) =>
      request<ProjectTag[]>(
        `/api/v1/project-tags${
          includeInactive ? "?include_inactive=true" : ""
        }`,
      ),
    create: (payload: {
      name: string;
      description?: string;
      color?: string;
      sort_order?: number;
    }) =>
      request<ProjectTag>("/api/v1/project-tags", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    update: (
      id: string,
      payload: {
        revision: number;
        name?: string;
        description?: string | null;
        color?: string | null;
        sort_order?: number;
        is_active?: boolean;
      },
    ) =>
      request<ProjectTag>(`/api/v1/project-tags/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
  },
  projects: {
    list: (params?: URLSearchParams) =>
      request<ProjectSummary[]>(
        `/api/v1/projects${params?.size ? `?${params}` : ""}`,
      ),
    get: (id: string) => request<Project>(`/api/v1/projects/${id}`),
    duplicates: (name: string) =>
      request<DuplicateCandidate[]>(
        `/api/v1/projects/duplicate-candidates?name=${encodeURIComponent(name)}`,
      ),
    create: (payload: Record<string, unknown>) =>
      request<Project>("/api/v1/projects", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    update: (id: string, payload: Record<string, unknown>) =>
      request<Project>(`/api/v1/projects/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    transition: (
      id: string,
      revision: number,
      status: string,
      reason?: string,
    ) =>
      request<Project>(`/api/v1/projects/${id}/transition`, {
        method: "POST",
        body: JSON.stringify({ revision, status, reason: reason || null }),
      }),
    addMember: (id: string, revision: number, userId: string) =>
      request<void>(`/api/v1/projects/${id}/members`, {
        method: "POST",
        body: JSON.stringify({ revision, user_id: userId }),
      }),
    addTag: (id: string, revision: number, tagId: string) =>
      request<void>(`/api/v1/projects/${id}/tags`, {
        method: "POST",
        body: JSON.stringify({ revision, tag_id: tagId }),
      }),
    addAlias: (id: string, revision: number, value: string) =>
      request<void>(`/api/v1/projects/${id}/aliases`, {
        method: "POST",
        body: JSON.stringify({ revision, value }),
      }),
    mergePreview: (id: string, targetProjectId: string) =>
      request<ProjectMergePreview>(
        `/api/v1/projects/${id}/merge-preview?target_project_id=${encodeURIComponent(
          targetProjectId,
        )}`,
      ),
    merge: (
      id: string,
      payload: {
        source_revision: number;
        target_project_id: string;
        target_revision: number;
        reason: string;
      },
    ) =>
      request<ProjectMergeResult>(`/api/v1/projects/${id}/merge`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
  },
  opportunities: {
    list: () => request<Opportunity[]>("/api/v1/opportunities"),
    get: (id: string) =>
      request<Opportunity>(`/api/v1/opportunities/${id}`),
    create: (payload: {
      name: string;
      customer_name: string | null;
      description: string | null;
      owner_id: string | null;
      member_ids: string[];
    }) =>
      request<Opportunity>("/api/v1/opportunities", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    recordProgress: (
      id: string,
      payload: {
        revision: number;
        week_start: string;
        business_stage: string;
        attention_status: string;
        progress_percent: number;
        summary: string;
        output_summary: string | null;
      },
    ) =>
      request(`/api/v1/opportunities/${id}/progress`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    convertToProject: (
      id: string,
      revision: number,
      project: Record<string, unknown>,
    ) =>
      request<{
        opportunity_id: string;
        opportunity_revision: number;
        project: Project;
      }>(`/api/v1/opportunities/${id}/convert-to-project`, {
        method: "POST",
        body: JSON.stringify({ revision, project }),
      }),
  },
  tasks: {
    list: (params?: URLSearchParams) =>
      request<Task[]>(`/api/v1/tasks${params?.size ? `?${params}` : ""}`),
    create: (payload: Record<string, unknown>) =>
      request<Task>("/api/v1/tasks", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    update: (
      id: string,
      payload: {
        revision: number;
        title?: string;
        description?: string | null;
        priority?: string;
        due_date?: string | null;
        collaborator_ids?: string[];
      },
    ) =>
      request<Task>(`/api/v1/tasks/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    reassign: (
      id: string,
      payload: {
        revision: number;
        owner_id: string;
        reason: string;
      },
    ) =>
      request<Task>(`/api/v1/tasks/${id}/reassign`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    createRelation: (payload: {
      source_task_id: string;
      target_task_id: string;
      label: string;
    }) =>
      request("/api/v1/tasks/relations", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    transition: (
      id: string,
      payload: {
        revision: number;
        status: string;
        blocker_reason?: string;
        result?: string;
        cancel_reason?: string;
        complete_descendants?: boolean;
      },
    ) =>
      request<Task>(`/api/v1/tasks/${id}/transition`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    updateProgress: (
      id: string,
      payload: {
        revision: number;
        enabled: boolean;
        percent?: number | null;
        result?: string | null;
        reason?: string | null;
      },
    ) =>
      request<Task>(`/api/v1/tasks/${id}/progress`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    progressHistory: (id: string) =>
      request<TaskProgressHistory[]>(`/api/v1/tasks/${id}/progress-history`),
    remove: (id: string, revision: number, reason?: string | null) =>
      request<void>(`/api/v1/tasks/${id}`, {
        method: "DELETE",
        body: JSON.stringify({ revision, reason: reason || null }),
      }),
  },
  records: {
    list: (params?: URLSearchParams) =>
      request<WorkRecord[]>(
        `/api/v1/work-records${params?.size ? `?${params}` : ""}`,
      ),
    occupancy: (workDate: string, excludeRecordId?: string | null) => {
      const params = new URLSearchParams({ date: workDate });
      if (excludeRecordId) params.set("exclude_record_id", excludeRecordId);
      return request<{ date: string; time_blocks: TimeBlock[] }>(
        `/api/v1/work-records/occupancy?${params}`,
      );
    },
    create: (payload: Record<string, unknown>) =>
      request<WorkRecord>("/api/v1/work-records", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    update: (id: string, payload: Record<string, unknown>) =>
      request<WorkRecord>(`/api/v1/work-records/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    delete: (id: string, revision: number, reason?: string | null) =>
      request<void>(`/api/v1/work-records/${id}`, {
        method: "DELETE",
        body: JSON.stringify({ revision, reason: reason || null }),
      }),
    quickCreate: (payload: Record<string, unknown>) =>
      request<WorkRecordQuickCreateResult>(
        "/api/v1/work-records/quick-create",
        {
          method: "POST",
          body: JSON.stringify(payload),
        },
      ),
  },
  ai: {
    status: () => request<AIStatus>("/api/v1/ai/status"),
    providers: () =>
      request<AIProviderOption[]>("/api/v1/ai/providers"),
    configuration: () =>
      request<AIConfiguration>("/api/v1/ai/configuration"),
    testConfiguration: (payload: {
      provider: string;
      access_mode: string;
      model: string;
      api_key: string;
    }) =>
      request<AIConfigurationTestResult>("/api/v1/ai/configuration/test", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    saveConfiguration: (payload: {
      provider: string;
      access_mode: string;
      model: string;
      api_key: string;
      verification_token: string;
      revision: number | null;
    }) =>
      request<AIConfiguration>("/api/v1/ai/configuration", {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    chat: (prompt: string, clientRequestId?: string) =>
      request<AIChatResult>("/api/v1/ai/chat", {
        method: "POST",
        body: JSON.stringify({ prompt, client_request_id: clientRequestId }),
      }),
    history: () =>
      request<{
        messages: Array<{ role: "user" | "assistant"; content: string }>;
      }>("/api/v1/ai/chat/history"),
    clearHistory: () =>
      request<{ cleared: number }>("/api/v1/ai/chat/history", {
        method: "DELETE",
      }),
  },
  weeklyReports: {
    current: () =>
      request<CurrentWeeklyReport>("/api/v1/weekly-reports/current"),
    list: () => request<WeeklyReport[]>("/api/v1/weekly-reports"),
    teamSummaries: () =>
      request<TeamWeeklySummary[]>("/api/v1/weekly-reports/team-summaries"),
    generateCurrent: () =>
      request<WeeklyReport>("/api/v1/weekly-reports/current/generate", {
        method: "POST",
      }),
    saveDraft: (id: string, revision: number, content: string) =>
      request<WeeklyReport>(`/api/v1/weekly-reports/${id}/draft`, {
        method: "PATCH",
        body: JSON.stringify({ revision, content }),
      }),
    submit: (
      id: string,
      revision: number,
      overwriteConfirmed: boolean,
    ) =>
      request<WeeklyReport>(`/api/v1/weekly-reports/${id}/submit`, {
        method: "POST",
        body: JSON.stringify({
          revision,
          overwrite_confirmed: overwriteConfirmed,
        }),
      }),
  },
  dashboard: {
    get: (weekStart?: string) =>
      request<Dashboard>(
        `/api/v1/dashboard${
          weekStart
            ? `?week_start=${encodeURIComponent(weekStart)}`
            : ""
        }`,
      ),
    recordProgress: (
      opportunityId: string,
      payload: {
        revision: number;
        week_start: string;
        business_stage: string;
        attention_status: string;
        progress_percent: number;
        summary: string;
        output_summary: string | null;
      },
    ) =>
      request(`/api/v1/opportunities/${opportunityId}/progress`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    generateTeamSummary: (weekStart: string, force: boolean) =>
      request<TeamWeeklySummary>(
        `/api/v1/dashboard/team-summary?week_start=${encodeURIComponent(
          weekStart,
        )}`,
        {
          method: "POST",
          body: JSON.stringify({ force }),
        },
      ),
  },
};
