export type UserRole =
  | "member"
  | "team_leader"
  | "system_admin"
  | "super_admin";

export type PermissionKey =
  | "dashboard.opportunity.view"
  | "dashboard.opportunity.progress"
  | "dashboard.opportunity.create"
  | "dashboard.work.view"
  | "dashboard.overview.view"
  | "dashboard.team_summary.generate"
  | "projects.view"
  | "projects.edit"
  | "projects.create"
  | "departments.view"
  | "departments.manage"
  | "department_works.view"
  | "department_works.edit"
  | "department_works.create"
  | "tasks.view"
  | "tasks.edit"
  | "tasks.create"
  | "work_records.view"
  | "work_records.manage"
  | "weekly_reports.view"
  | "weekly_reports.manage"
  | "ai.use"
  | "settings.users.manage"
  | "settings.tags.manage"
  | "settings.ai.manage"
  | "settings.audit.view";

export interface User {
  id: string;
  login_name: string;
  display_name: string;
  role: UserRole;
  leader_id: string | null;
  primary_department_id: string | null;
  avatar_key: string | null;
  is_active: boolean;
  must_change_password: boolean;
  revision: number;
}

export interface Department {
  id: string;
  name: string;
  leader_id: string | null;
  is_active: boolean;
  created_by: string;
  revision: number;
  created_at: string;
  updated_at: string;
}

export type DepartmentWorkStatus = "in_progress" | "completed" | "archived";

export type DepartmentWorkVisibility = "department_only" | "public";

export interface DepartmentWork {
  id: string;
  code: string;
  name: string;
  description: string | null;
  department_id: string;
  department_name: string;
  owner_id: string;
  owner_display_name: string;
  status: DepartmentWorkStatus;
  visibility: DepartmentWorkVisibility;
  created_by: string;
  revision: number;
  created_at: string;
  updated_at: string;
}

export type UserCandidate = Pick<
  User,
  "id" | "display_name" | "avatar_key" | "primary_department_id"
>;

export interface AuthContext {
  user: User;
  permissions: PermissionKey[];
  csrf_token: string;
  expires_at: string;
}

export interface AuditEvent {
  id: string;
  request_id: string | null;
  actor_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before_data: Record<string, unknown> | null;
  after_data: Record<string, unknown> | null;
  result: string;
  detail: Record<string, unknown> | null;
  client_ip: string | null;
  created_at: string;
}

export interface PermissionDefinition {
  key: PermissionKey;
  group: string;
  group_label: string;
  label: string;
  description: string;
  system_admin_assignable: boolean;
  requires_team_scope: boolean;
}

export interface UserPermissions {
  user_id: string;
  revision: number;
  assigned_permissions: PermissionKey[];
  effective_permissions: PermissionKey[];
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

export interface ProjectMergePreview {
  source_project_id: string;
  target_project_id: string;
  source_name: string;
  target_name: string;
  task_count: number;
  work_record_count: number;
  deliverable_count: number;
  progress_count: number;
  invalidated_task_relation_count: number;
  child_project_count: number;
  new_member_count: number;
  new_tag_count: number;
  aliases_to_move: string[];
}

export interface ProjectMergeResult {
  merge_id: string;
  source_project_id: string;
  target_project_id: string;
  moved_counts: Record<string, number>;
}

export type TaskStatus =
  | "todo"
  | "in_progress"
  | "blocked"
  | "done"
  | "cancelled";

export interface Task {
  id: string;
  project_id: string | null;
  department_work_id: string | null;
  parent_id: string | null;
  level: number;
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
  progress_enabled: boolean;
  progress_percent: number | null;
  revision: number;
  created_at: string;
  updated_at: string;
  collaborator_ids: string[];
}

export interface TaskProgressHistory {
  id: string;
  task_id: string;
  from_enabled: boolean;
  to_enabled: boolean;
  from_percent: number | null;
  to_percent: number | null;
  from_status: string;
  to_status: string;
  reason: string | null;
  changed_by: string;
  changed_at: string;
}

export type TaskTimeScope = "today" | "week" | "all";

export interface QuickTaskCreate {
  title: string;
  description?: string | null;
  owner_id?: string | null;
  collaborator_ids?: string[];
  priority?: "p0" | "p1" | "p2";
  due_date?: string | null;
  parent_id?: string | null;
}

export interface WorkRecordQuickCreateResult {
  work_record: WorkRecord;
  created_project_id: string | null;
  created_department_work_id: string | null;
  created_task_id: string | null;
  replayed: boolean;
}

export interface Deliverable {
  id: string;
  project_id: string | null;
  department_work_id: string | null;
  task_id: string | null;
  work_record_id: string | null;
  name: string;
  url: string;
  revision: number;
  created_at: string;
}

/** 工作时间块：当天 00:00 起的分钟数区间，30 的倍数 */
export interface TimeBlock {
  /** 起始分钟（含），30 的倍数 */
  start: number;
  /** 结束分钟（不含），30 的倍数 */
  end: number;
}

export interface WorkRecord {
  id: string;
  author_id: string;
  author_display_name: string;
  author_avatar_key: string | null;
  work_date: string;
  content: string;
  minutes: number;
  /** 具体工作区间；后端未返回时按 [] 处理 */
  time_blocks: TimeBlock[];
  project_id: string | null;
  project_name: string | null;
  department_work_id: string | null;
  department_work_name: string | null;
  source_type: "project" | "department_work" | null;
  source_id: string | null;
  source_name: string | null;
  task_id: string | null;
  task_title: string | null;
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

export type ChangelogCategory =
  | "feature"
  | "improvement"
  | "fix"
  | "removal"
  | "release";

export interface ChangelogEntry {
  id: string;
  occurred_at: string;
  category: ChangelogCategory;
  title: string;
  body: string;
  created_by: string;
  created_by_name: string;
  updated_by: string;
  updated_by_name: string;
  revision: number;
  created_at: string;
  updated_at: string;
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

export type BusinessStage =
  | "lead"
  | "requirement"
  | "solution_exchange"
  | "solution_confirm"
  | "poc"
  | "tender"
  | "won";

export type AttentionStatus = "focus" | "steady" | "coordinate";

export interface DashboardWeek {
  week_start: string;
  week_end: string;
  label: string;
  is_current: boolean;
}

export interface DashboardMember {
  id: string;
  display_name: string;
  role: string;
  avatar_key: string | null;
  submitted: boolean;
  submitted_at: string | null;
  weekly_minutes: number | null;
  submitted_weeks: string[];
  department_id: string | null;
  department_name: string | null;
}

export type ManagementScopeType = "all_led" | "department" | "other_direct";

export interface ManagementScopeOption {
  scope_type: ManagementScopeType;
  department_id: string | null;
  department_name: string | null;
  member_count: number;
}

export interface ManagementScope {
  scope_type: ManagementScopeType;
  department_id: string | null;
  options: ManagementScopeOption[];
  other_direct_count: number;
}

export interface DashboardWorkItem {
  id: string;
  author_id: string;
  author_display_name: string;
  author_avatar_key: string | null;
  content: string;
  minutes: number;
  risk: string | null;
  next_action: string | null;
}

export interface DashboardTask {
  id: string;
  title: string;
  status: TaskStatus;
  priority: "p0" | "p1" | "p2";
  owner_id: string;
  owner_display_name: string;
  owner_avatar_key: string | null;
  due_date: string | null;
  blocker_reason: string | null;
  result: string | null;
}

export interface DashboardProjectMember {
  id: string;
  display_name: string;
  avatar_key: string | null;
}

export interface DashboardStageHistory {
  id: string;
  week_start: string;
  business_stage: BusinessStage;
  progress_percent: number;
  created_at: string;
}

export interface DashboardProject {
  id: string;
  code: string;
  name: string;
  type_label: string;
  can_manage: boolean;
  lifecycle_status: ProjectStatus;
  business_stage: BusinessStage;
  attention_status: AttentionStatus;
  progress_percent: number;
  weekly_minutes: number | null;
  work_summary: string;
  output_summary: string;
  has_week_progress: boolean;
  people: DashboardProjectMember[];
  tasks: DashboardTask[];
  work_items: DashboardWorkItem[];
  stage_history: DashboardStageHistory[];
}

export type OpportunityStatus = "active" | "won" | "lost" | "archived";

export interface DashboardOpportunity {
  id: string;
  code: string;
  name: string;
  customer_name: string | null;
  description: string | null;
  owner_id: string;
  owner_display_name: string;
  owner_avatar_key: string | null;
  can_manage: boolean;
  can_convert: boolean;
  status: OpportunityStatus;
  business_stage: BusinessStage;
  attention_status: AttentionStatus;
  progress_percent: number;
  work_summary: string;
  output_summary: string;
  has_week_progress: boolean;
  linked_project_id: string | null;
  linked_project_code: string | null;
  linked_project_name: string | null;
  linked_project_status: ProjectStatus | null;
  people: DashboardProjectMember[];
  stage_history: DashboardStageHistory[];
  revision: number;
}

export interface Opportunity extends DashboardOpportunity {
  members: DashboardProjectMember[];
  project_linked_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectCreationDraft {
  opportunity_id: string;
  opportunity_revision: number;
  opportunity_code: string;
  name: string;
  description: string;
  owner_id: string;
}

export interface DashboardDeliverable {
  id: string;
  name: string;
  url: string;
  project_id: string;
  project_name: string;
  author_id: string | null;
  author_display_name: string | null;
}

export interface DashboardTaskLink {
  id: string;
  source_task_id: string;
  target_task_id: string;
  label: string;
}

export interface DashboardMetrics {
  tracking_count: number;
  focus_count: number;
  stage_advanced_count: number;
  deliverable_count: number;
  coordinate_count: number;
  total_minutes: number;
  submitted_count: number;
  member_count: number;
}

export interface DashboardWeekTrend {
  week_start: string;
  week_end: string;
  total_minutes: number;
  deliverable_count: number;
  submitted_count: number;
  member_count: number;
}

export interface DashboardStageCount {
  business_stage: BusinessStage;
  count: number;
}

export interface DashboardTimelineEvent {
  id: string;
  opportunity_id: string;
  opportunity_name: string;
  week_start: string;
  business_stage: BusinessStage;
  attention_status: AttentionStatus;
  summary: string;
  created_at: string;
}

export interface TeamWeeklySummary {
  id: string;
  week_start: string;
  week_end: string;
  content: string;
  generated_by: string;
  forced: boolean;
  submitted_count: number;
  expected_count: number;
  included_leader_count: number;
  source_reports: Array<{
    report_id: string;
    author_id: string;
    submission_version: number;
    order: number;
    depth: number;
  }> | null;
  generation_model: string;
  generation_usage: AIChatResult["usage"] | null;
  scope_type: ManagementScopeType | string;
  department_id: string | null;
  scope_key: string;
  created_at: string;
  revision: number;
}

export interface Dashboard {
  accessible_pages: Array<"opp" | "work" | "overview">;
  selected_week: DashboardWeek;
  weeks: DashboardWeek[];
  metrics: DashboardMetrics;
  members: DashboardMember[];
  opportunities: DashboardOpportunity[];
  projects: DashboardProject[];
  deliverables: DashboardDeliverable[];
  task_links: DashboardTaskLink[];
  trends: DashboardWeekTrend[];
  stage_distribution: DashboardStageCount[];
  stage_timeline: DashboardTimelineEvent[];
  latest_team_summary: TeamWeeklySummary | null;
  management_scope: ManagementScope | null;
}
