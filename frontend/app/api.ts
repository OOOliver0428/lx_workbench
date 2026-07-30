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
  DuplicateCandidate,
  Project,
  ProjectSummary,
  ProjectTag,
  Task,
  User,
  CurrentWeeklyReport,
  Dashboard,
  TeamWeeklySummary,
  PermissionDefinition,
  PermissionKey,
  WeeklyReport,
  WorkRecord,
  UserPermissions,
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
    list: () => request<User[]>("/api/v1/users"),
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
      },
    ) =>
      request<User>(`/api/v1/users/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
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
    list: () => request<ProjectTag[]>("/api/v1/project-tags"),
    create: (payload: {
      name: string;
      description?: string;
      color?: string;
    }) =>
      request<ProjectTag>("/api/v1/project-tags", {
        method: "POST",
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
  },
  tasks: {
    list: (params?: URLSearchParams) =>
      request<Task[]>(`/api/v1/tasks${params?.size ? `?${params}` : ""}`),
    create: (payload: Record<string, unknown>) =>
      request<Task>("/api/v1/tasks", {
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
      },
    ) =>
      request<Task>(`/api/v1/tasks/${id}/transition`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
  },
  records: {
    list: (params?: URLSearchParams) =>
      request<WorkRecord[]>(
        `/api/v1/work-records${params?.size ? `?${params}` : ""}`,
      ),
    create: (payload: Record<string, unknown>) =>
      request<WorkRecord>("/api/v1/work-records", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
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
    chat: (prompt: string) =>
      request<AIChatResult>("/api/v1/ai/chat", {
        method: "POST",
        body: JSON.stringify({ prompt }),
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
      projectId: string,
      payload: {
        week_start: string;
        business_stage: string;
        attention_status: string;
        progress_percent: number;
        summary: string;
        output_summary: string | null;
      },
    ) =>
      request(`/api/v1/projects/${projectId}/progress`, {
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
