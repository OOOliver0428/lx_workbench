import type { AuditEvent } from "./types";

export const ACTION_LABELS: Record<string, string> = {
  "auth.login": "登录系统",
  "auth.logout": "退出登录",
  "auth.password.change": "修改密码",
  "user.create": "创建用户",
  "user.update": "更新用户资料",
  "user.freeze": "冻结账号",
  "user.unfreeze": "解冻账号",
  "user.leader.update": "调整直属 Leader",
  "user.permissions.replace": "配置用户权限",
  "user.department.assign": "分配用户部门",
  "profile.avatar.update": "更新个人头像",
  "department.create": "创建部门",
  "department.update": "更新部门",
  "department.delete": "删除部门",
  "project.create_proposal": "提交立项申请",
  "project.update": "更新项目",
  "project.transition": "项目状态流转",
  "project.alias.add": "添加项目别名",
  "project.tag.add": "添加项目标签",
  "project.tag.remove": "移除项目标签",
  "project.member.add": "添加项目成员",
  "project.member.remove": "移除项目成员",
  "project.merge": "合并项目",
  "project.progress.record": "记录项目进展",
  "task.create": "创建任务",
  "task.update": "更新任务",
  "task.transition": "任务状态流转",
  "task.progress.update": "更新任务进度",
  "task.delete": "删除任务",
  "task.reassign": "转派任务",
  "task.relation.create": "创建任务关联",
  "work_record.create": "创建工作记录",
  "work_record.update": "更新工作记录",
  "work_record.delete": "删除工作记录",
  "weekly_report.draft.save": "保存周报草稿",
  "weekly_report.generate": "生成周报",
  "weekly_report.regenerate": "重新生成周报",
  "weekly_report.submit": "提交周报",
  "weekly_report.resubmit": "重新提交周报",
  "team_weekly_summary.generate": "生成团队周报汇总",
  "team_weekly_summary.regenerate": "重新生成团队周报汇总",
  "changelog.create": "创建更新日志",
  "changelog.update": "编辑更新日志",
  "changelog.delete": "删除更新日志",
  "changelog.reorder": "调整更新日志排序",
  "department_work.create": "创建部门工作",
  "department_work.update": "更新部门工作",
  "department_work.transition": "部门工作状态流转",
  "department_work.delete": "删除部门工作",
  "opportunity.create": "创建商机",
  "opportunity.delete": "删除商机",
  "opportunity.progress.record": "记录商机进展",
  "opportunity.project.link": "商机关联项目",
  "project_tag.create": "创建项目标签",
  "project_tag.update": "更新项目标签",
  "ai.configuration.test": "测试大模型配置",
  "ai.configuration.save": "保存大模型配置",
  "ai.chat": "AI 对话",
  "ai.chat.clear": "清空 AI 对话记录",
};

export const ENTITY_TYPE_LABELS: Record<string, string> = {
  user: "用户",
  department: "部门",
  project: "项目",
  project_progress: "项目进展",
  task: "任务",
  task_relation: "任务关联",
  work_record: "工作记录",
  weekly_report: "周报",
  team_weekly_summary: "团队周报汇总",
  changelog_entry: "更新日志",
  department_work: "部门工作",
  opportunity: "商机",
  opportunity_progress: "商机进展",
  project_tag: "项目标签",
  ai: "AI 助手",
  ai_configuration: "大模型配置",
  ai_chat: "AI 对话",
};

export const SYSTEM_ACTOR_FILTER = "__system__";
export const SYSTEM_ACTOR_LABEL = "系统";

export interface AuditEventFilter {
  actorId?: string;
  action?: string;
  from?: string;
  to?: string;
}

export interface AuditFilterOption {
  value: string;
  label: string;
}

export function formatAuditAction(action: string): string {
  return ACTION_LABELS[action] ?? action;
}

export function formatAuditEntity(
  entityType: string,
  entityId: string | null,
): string {
  const label = ENTITY_TYPE_LABELS[entityType] ?? entityType;
  if (!entityId) return label;
  return `${label} · ${entityId.slice(0, 8)}`;
}

export function formatAuditActor(
  actorId: string | null,
  actorName: string | null,
): string {
  if (actorName) return actorName;
  return actorId ? "未知用户" : SYSTEM_ACTOR_LABEL;
}

export function collectAuditActors(events: AuditEvent[]): AuditFilterOption[] {
  const nameById = new Map<string, string>();
  let hasSystem = false;
  for (const event of events) {
    if (event.actor_id === null) {
      hasSystem = true;
    } else if (!nameById.has(event.actor_id)) {
      nameById.set(event.actor_id, formatAuditActor(event.actor_id, event.actor_name));
    }
  }
  const options = [...nameById.entries()].map(([value, label]) => ({
    value,
    label,
  }));
  options.sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));
  if (hasSystem) {
    options.unshift({ value: SYSTEM_ACTOR_FILTER, label: SYSTEM_ACTOR_LABEL });
  }
  return options;
}

export function collectAuditActions(events: AuditEvent[]): AuditFilterOption[] {
  const actions = [...new Set(events.map((event) => event.action))];
  actions.sort((a, b) =>
    formatAuditAction(a).localeCompare(formatAuditAction(b), "zh-CN"),
  );
  return actions.map((action) => ({
    value: action,
    label: formatAuditAction(action),
  }));
}

export function hasActiveAuditFilters(filters: AuditEventFilter): boolean {
  return Boolean(
    filters.actorId || filters.action || filters.from || filters.to,
  );
}

export function filterAuditEvents(
  events: AuditEvent[],
  filters: AuditEventFilter,
): AuditEvent[] {
  const fromTime = parseFilterTime(filters.from, false);
  const toTime = parseFilterTime(filters.to, true);
  return events.filter((event) => {
    if (filters.actorId) {
      if (filters.actorId === SYSTEM_ACTOR_FILTER) {
        if (event.actor_id !== null) return false;
      } else if (event.actor_id !== filters.actorId) {
        return false;
      }
    }
    if (filters.action && event.action !== filters.action) return false;
    const created = new Date(event.created_at).getTime();
    if (fromTime !== null && created < fromTime) return false;
    if (toTime !== null && created > toTime) return false;
    return true;
  });
}

function parseFilterTime(
  value: string | undefined,
  endOfMinute: boolean,
): number | null {
  if (!value) return null;
  const time = new Date(value).getTime();
  if (Number.isNaN(time)) return null;
  if (endOfMinute && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) {
    return time + 59_999;
  }
  return time;
}
