export type UserRole =
  | "member"
  | "team_leader"
  | "system_admin"
  | "super_admin";

export interface User {
  id: string;
  login_name: string;
  display_name: string;
  role: UserRole;
  leader_id: string | null;
  avatar_key: string | null;
  is_active: boolean;
  must_change_password: boolean;
  revision: number;
}

export interface AuthContext {
  user: User;
  csrf_token: string;
  expires_at: string;
}

export interface AvatarOption {
  id: string;
  label: string;
  style: string;
  style_label: string;
  character: number;
  url: string;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  request_id: string | null;
  details: Record<string, unknown> | null;
}

export interface ProjectTag {
  id: string;
  name: string;
  description: string | null;
  color: string | null;
  sort_order: number;
  is_active: boolean;
  revision: number;
}

export interface ProjectAlias {
  id: string;
  value: string;
  source: string;
  created_at: string;
}

export interface ProjectMember {
  user_id: string;
  display_name: string;
  avatar_key: string | null;
  role: "owner" | "member";
  joined_at: string;
  left_at: string | null;
}

export type ProjectStatus =
  | "pending"
  | "active"
  | "paused"
  | "completed"
  | "archived"
  | "rejected"
  | "merged";

export interface ProjectSummary {
  id: string;
  code: string;
  name: string;
  status: ProjectStatus;
  parent_project_id: string | null;
  owner_id: string;
  owner_display_name: string;
  owner_avatar_key: string | null;
  planned_start_date: string | null;
  planned_end_date: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
  tags: ProjectTag[];
}

export interface Project extends ProjectSummary {
  description: string | null;
  proposed_by: string;
  approved_by: string | null;
  approved_at: string | null;
  rejected_reason: string | null;
  merged_into_project_id: string | null;
  aliases: ProjectAlias[];
  members: ProjectMember[];
}

export interface DuplicateCandidate {
  project_id: string;
  code: string;
  name: string;
  matched_value: string;
  match_type: string;
  similarity: number;
  status: string;
}

export type TaskStatus =
  | "todo"
  | "in_progress"
  | "blocked"
  | "done"
  | "cancelled";

export interface Task {
  id: string;
  project_id: string;
  title: string;
  description: string | null;
  owner_id: string;
  created_by: string;
  priority: "p0" | "p1" | "p2";
  status: TaskStatus;
  due_date: string | null;
  blocker_reason: string | null;
  result: string | null;
  cancel_reason: string | null;
  started_at: string | null;
  completed_at: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
  collaborator_ids: string[];
}

export interface Deliverable {
  id: string;
  project_id: string;
  task_id: string | null;
  work_record_id: string | null;
  name: string;
  url: string;
  revision: number;
  created_at: string;
}

export interface WorkRecord {
  id: string;
  author_id: string;
  author_display_name: string;
  author_avatar_key: string | null;
  work_date: string;
  content: string;
  minutes: number;
  project_id: string | null;
  task_id: string | null;
  risk: string | null;
  next_action: string | null;
  last_edited_by: string;
  last_editor_display_name: string;
  last_editor_avatar_key: string | null;
  delegated_edit_reason: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
  deliverables: Deliverable[];
}

export interface AIStatus {
  configured: boolean;
  provider: string;
  model: string;
}

export interface AIChatResult {
  answer: string;
  model: string;
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

export interface WeeklyReport {
  id: string;
  author_id: string;
  week_start: string;
  week_end: string;
  content: string;
  submitted_content: string | null;
  submitted_to_id: string | null;
  generated_at: string | null;
  generation_model: string | null;
  generation_usage: AIChatResult["usage"] | null;
  submitted_at: string | null;
  submission_version: number;
  revision: number;
  created_at: string;
  updated_at: string;
  has_unsubmitted_changes: boolean;
}

export interface CurrentWeeklyReport {
  week_start: string;
  week_end: string;
  report: WeeklyReport | null;
}

export interface WeeklyReportInboxItem {
  id: string;
  author_id: string;
  author_display_name: string;
  week_start: string;
  week_end: string;
  content: string;
  submitted_at: string;
  submission_version: number;
}

export interface AIProviderAccessMode {
  id: string;
  name: string;
  description: string;
  base_url: string;
  protocol: "openai" | "anthropic";
  default_model: string;
  models: string[];
  docs_url: string;
}

export interface AIProviderOption {
  id: string;
  name: string;
  default_access_mode: string;
  access_modes: AIProviderAccessMode[];
  api_key_url: string;
}

export interface AIConfiguration {
  configured: boolean;
  source: "database" | "environment" | "none";
  provider: string | null;
  provider_name: string | null;
  access_mode: string | null;
  access_mode_name: string | null;
  protocol: string | null;
  base_url: string | null;
  model: string | null;
  api_key_hint: string | null;
  tested_at: string | null;
  updated_at: string | null;
  revision: number | null;
  encryption_ready: boolean;
}

export interface AIConfigurationTestResult {
  success: boolean;
  provider: string;
  access_mode: string;
  model: string;
  message: string;
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
  verification_token: string;
  expires_at: string;
}
