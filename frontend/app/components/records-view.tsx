"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiClientError } from "../api";
import { createClientMessageId } from "../client-id";
import { localDateInputValue } from "../date-utils";
import type {
  Department,
  DepartmentWork,
  PermissionKey,
  ProjectSummary,
  Task,
  TimeBlock,
  UserCandidate,
  UserRole,
  WorkRecord,
} from "../types";
import { AvatarImage } from "./avatar";
import { ArrowUpRight, Plus } from "./icons";
import { TimeBlockPicker } from "./time-block-picker";
import { EmptyState, InlineNotice, Modal } from "./ui";

type RecordSourceType = "project" | "department_work" | "none";
type QuickSourceType = RecordSourceType | "new_project" | "new_department_work";

export function RecordsView({
  canManage,
  canViewProjects,
  canViewTasks,
}: {
  canManage: boolean;
  canViewProjects: boolean;
  canViewTasks: boolean;
}) {
  const [records, setRecords] = useState<WorkRecord[]>([]);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [departmentWorks, setDepartmentWorks] = useState<DepartmentWork[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [users, setUsers] = useState<UserCandidate[]>([]);
  const [projectId, setProjectId] = useState("");
  const [departmentWorkId, setDepartmentWorkId] = useState("");
  const [unassignedOnly, setUnassignedOnly] = useState(false);
  const [currentWeekOnly, setCurrentWeekOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [quickCreateOpen, setQuickCreateOpen] = useState(false);
  const [editingRecord, setEditingRecord] = useState<WorkRecord | null>(null);
  const [deletingRecordId, setDeletingRecordId] = useState("");
  const [currentUserId, setCurrentUserId] = useState("");
  const [currentUserRole, setCurrentUserRole] = useState<UserRole>("member");
  const [currentDepartmentId, setCurrentDepartmentId] = useState<
    string | null
  >(null);
  const [permissions, setPermissions] = useState<PermissionKey[]>([]);

  useEffect(() => {
    let cancelled = false;
    api.auth
      .me()
      .then((context) => {
        if (cancelled) return;
        setCurrentUserId(context.user.id);
        setCurrentUserRole(context.user.role);
        setCurrentDepartmentId(context.user.primary_department_id);
        setPermissions(context.permissions);
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(
            caught instanceof ApiClientError
              ? caught.message
              : "当前用户信息加载失败",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const canViewDepartmentWorks = permissions.includes("department_works.view");
  const canCreateProjects = permissions.includes("projects.create");
  const canCreateDepartmentWorks = permissions.includes(
    "department_works.create",
  );
  const canCreateTasks = permissions.includes("tasks.create");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (projectId) params.set("project_id", projectId);
      if (departmentWorkId) params.set("department_work_id", departmentWorkId);
      if (unassignedOnly) params.set("unassigned_only", "true");
      if (currentWeekOnly) params.set("current_week_only", "true");
      const [recordRows, projectRows, departmentWorkRows, taskRows] =
        await Promise.all([
          api.records.list(params),
          canViewProjects ? api.projects.list() : Promise.resolve([]),
          canViewDepartmentWorks
            ? api.departmentWorks.list()
            : Promise.resolve([]),
          canViewTasks ? api.tasks.list() : Promise.resolve([]),
        ]);
      setRecords(recordRows);
      setProjects(projectRows);
      setDepartmentWorks(departmentWorkRows);
      setTasks(taskRows);
      // 负责人/部门候选：失败（如无候选人权限）时降级为空，弹窗隐藏对应字段
      if (canManage) {
        const [userRows, departmentRows] = await Promise.all([
          api.users.candidates().catch(() => []),
          canViewDepartmentWorks
            ? api.departments.list().catch(() => [])
            : Promise.resolve([]),
        ]);
        setUsers(userRows);
        setDepartments(departmentRows.filter((item) => item.is_active));
      }
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "工作记录加载失败",
      );
    } finally {
      setLoading(false);
    }
  }, [
    canManage,
    canViewDepartmentWorks,
    canViewProjects,
    canViewTasks,
    currentWeekOnly,
    departmentWorkId,
    projectId,
    unassignedOnly,
  ]);

  useEffect(() => {
    const timeout = window.setTimeout(load, 0);
    return () => window.clearTimeout(timeout);
  }, [load]);

  const projectNames = useMemo(
    () => new Map(projects.map((project) => [project.id, project.name])),
    [projects],
  );
  const departmentWorkNames = useMemo(
    () => new Map(departmentWorks.map((work) => [work.id, work.name])),
    [departmentWorks],
  );
  const taskNames = useMemo(
    () => new Map(tasks.map((task) => [task.id, task.title])),
    [tasks],
  );
  const totalMinutes = records.reduce((sum, record) => sum + record.minutes, 0);
  const weekMinutes = useMemo(() => {
    const { start, end } = currentWeekRange();
    return records
      .filter((record) => record.work_date >= start && record.work_date <= end)
      .reduce((sum, record) => sum + record.minutes, 0);
  }, [records]);

  async function deleteRecord(record: WorkRecord) {
    if (!window.confirm(`确认删除 ${record.work_date} 的这条工作记录？`)) {
      return;
    }
    let reason: string | null = null;
    if (record.author_id !== currentUserId) {
      reason = window.prompt("代删他人记录必须填写原因：")?.trim() || null;
      if (!reason) {
        setError("已取消删除：代删他人记录必须填写原因。");
        return;
      }
    }
    setDeletingRecordId(record.id);
    setError("");
    try {
      await api.records.delete(record.id, record.revision, reason);
      await load();
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "工作记录删除失败",
      );
    } finally {
      setDeletingRecordId("");
    }
  }

  return (
    <div className="view-shell">
      <header className="view-header">
        <div>
          <p className="eyebrow">WORK LOG</p>
          <h1>工作记录</h1>
          <p>按项目或部门工作沉淀每天的有效工作，为后续周报归纳提供可追溯依据。</p>
        </div>
        {canManage ? (
          <button
            className="primary-button"
            onClick={() => setQuickCreateOpen(true)}
          >
            <Plus size={14} /> 记录工作
          </button>
        ) : null}
      </header>

      <section className="toolbar">
        <label className="select-filter select-wide">
          <span>关联项目</span>
          <select
            value={projectId}
            disabled={unassignedOnly || Boolean(departmentWorkId)}
            onChange={(event) => setProjectId(event.target.value)}
          >
            <option value="">全部项目</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        {canViewDepartmentWorks ? (
          <label className="select-filter select-wide">
            <span>关联部门工作</span>
            <select
              value={departmentWorkId}
              disabled={unassignedOnly || Boolean(projectId)}
              onChange={(event) => setDepartmentWorkId(event.target.value)}
            >
              <option value="">全部部门工作</option>
              {departmentWorks.map((work) => (
                <option key={work.id} value={work.id}>
                  {work.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="toggle-filter">
          <input
            type="checkbox"
            checked={unassignedOnly}
            onChange={(event) => setUnassignedOnly(event.target.checked)}
          />
          <span />
          仅看待归集
        </label>
        <label className="toggle-filter">
          <input
            type="checkbox"
            checked={currentWeekOnly}
            onChange={(event) => setCurrentWeekOnly(event.target.checked)}
          />
          <span />
          仅显示本周记录
        </label>
        <div className="toolbar-meta">
          <strong>{formatHours(totalMinutes)}</strong>
          <span>累计工时</span>
        </div>
        <div className="toolbar-meta">
          <strong>{formatHours(weekMinutes)}</strong>
          <span>本周工时</span>
        </div>
      </section>

      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
      {notice ? <InlineNotice tone="success">{notice}</InlineNotice> : null}
      <section className="record-timeline">
        {loading ? (
          <div className="list-loading">
            <i />
            <span>正在载入记录…</span>
          </div>
        ) : records.length ? (
          groupByDate(records).map(([date, dateRecords]) => (
            <div className="record-day" key={date}>
              <header>
                <strong>{humanDate(date)}</strong>
                <span>
                  {formatHours(
                    dateRecords.reduce((sum, record) => sum + record.minutes, 0),
                  )}
                </span>
              </header>
              <div className="record-day-content">
                {dateRecords.map((record) => (
                  <article className="record-card" key={record.id}>
                    <div className="record-project-line">
                      <div className="record-labels">
                        <span
                          className={record.source_id ? "linked" : "unassigned"}
                        >
                          {record.source_id
                            ? record.source_name ??
                              record.project_name ??
                              record.department_work_name ??
                              (record.source_type === "department_work"
                                ? departmentWorkNames.get(record.source_id)
                                : projectNames.get(record.source_id)) ??
                              "未知来源"
                            : "待归集"}
                        </span>
                        {record.source_type === "department_work" &&
                        record.source_id ? (
                          <span className="record-source-tag">部门工作</span>
                        ) : null}
                        <span className="record-author">
                          <AvatarImage
                            avatarKey={record.author_avatar_key}
                            displayName={record.author_display_name}
                            decorative
                          />
                          记录人：{record.author_display_name}
                        </span>
                      </div>
                      <div className="user-card-actions">
                        <strong>{formatHours(record.minutes)}</strong>
                        {canManage && currentUserId ? (
                          <>
                            <button
                              type="button"
                              className="text-button"
                              onClick={() => setEditingRecord(record)}
                            >
                              编辑
                            </button>
                            <button
                              type="button"
                              className="text-button"
                              disabled={deletingRecordId === record.id}
                              style={{ color: "var(--red)" }}
                              onClick={() => deleteRecord(record)}
                            >
                              {deletingRecordId === record.id
                                ? "删除中…"
                                : "删除"}
                            </button>
                          </>
                        ) : null}
                      </div>
                    </div>
                    <p>{record.content}</p>
                    {record.task_id ? (
                      <div className="record-task">
                        任务 ·{" "}
                        {record.task_title ??
                          taskNames.get(record.task_id) ??
                          "未知任务"}
                      </div>
                    ) : null}
                    {record.last_edited_by !== record.author_id ? (
                      <div className="record-editor-note">
                        最后由 {record.last_editor_display_name} 代编辑
                      </div>
                    ) : null}
                    {record.risk || record.next_action ? (
                      <dl className="record-meta">
                        {record.risk ? (
                          <div>
                            <dt>风险</dt>
                            <dd>{record.risk}</dd>
                          </div>
                        ) : null}
                        {record.next_action ? (
                          <div>
                            <dt>下一步</dt>
                            <dd>{record.next_action}</dd>
                          </div>
                        ) : null}
                      </dl>
                    ) : null}
                    {record.deliverables.length ? (
                      <div className="deliverables">
                        {record.deliverables.map((deliverable) => (
                          <a
                            key={deliverable.id}
                            href={deliverable.url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            <span><ArrowUpRight size={12} /></span>
                            {deliverable.name}
                          </a>
                        ))}
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            </div>
          ))
        ) : (
          <EmptyState
            title="还没有工作记录"
            description="记录今天完成的工作，并尽量关联到正确的项目或部门工作。"
          />
        )}
      </section>

      {quickCreateOpen && canManage ? (
        <QuickCreateModal
          projects={projects}
          departmentWorks={departmentWorks}
          departments={departments}
          tasks={tasks}
          users={users}
          currentUserId={currentUserId}
          currentUserRole={currentUserRole}
          currentDepartmentId={currentDepartmentId}
          canViewProjects={canViewProjects}
          canViewDepartmentWorks={canViewDepartmentWorks}
          canCreateProjects={canCreateProjects}
          canCreateDepartmentWorks={canCreateDepartmentWorks}
          canCreateTasks={canCreateTasks}
          onClose={() => setQuickCreateOpen(false)}
          onCreated={async (message) => {
            setQuickCreateOpen(false);
            setNotice(message);
            await load();
          }}
        />
      ) : null}
      {editingRecord && canManage && currentUserId ? (
        <RecordEditModal
          record={editingRecord}
          projects={projects}
          departmentWorks={departmentWorks}
          tasks={tasks}
          canViewDepartmentWorks={canViewDepartmentWorks}
          currentUserId={currentUserId}
          onClose={() => setEditingRecord(null)}
          onUpdated={async () => {
            setEditingRecord(null);
            await load();
          }}
        />
      ) : null}
    </div>
  );
}

function RecordEditModal({
  record,
  projects,
  departmentWorks,
  tasks,
  canViewDepartmentWorks,
  currentUserId,
  onClose,
  onUpdated,
}: {
  record: WorkRecord;
  projects: ProjectSummary[];
  departmentWorks: DepartmentWork[];
  tasks: Task[];
  canViewDepartmentWorks: boolean;
  currentUserId: string;
  onClose: () => void;
  onUpdated: () => void;
}) {
  const [sourceType, setSourceType] = useState<RecordSourceType>(
    record.source_type ?? "none",
  );
  const [selectedProject, setSelectedProject] = useState(
    record.project_id ?? "",
  );
  const [selectedDepartmentWork, setSelectedDepartmentWork] = useState(
    record.department_work_id ?? "",
  );
  const [selectedTask, setSelectedTask] = useState(record.task_id ?? "");
  const [pickedBlocks, setPickedBlocks] = useState<TimeBlock[]>(
    record.time_blocks ?? [],
  );
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const delegated = record.author_id !== currentUserId;
  const showDepartmentWorkSource =
    canViewDepartmentWorks || sourceType === "department_work";
  const visibleTasks = tasks.filter((task) => {
    if (sourceType === "project") {
      return selectedProject
        ? task.project_id === selectedProject
        : Boolean(task.project_id);
    }
    if (sourceType === "department_work") {
      return selectedDepartmentWork
        ? task.department_work_id === selectedDepartmentWork
        : Boolean(task.department_work_id);
    }
    return true;
  });

  function changeSourceType(value: RecordSourceType) {
    setSourceType(value);
    const task = tasks.find((item) => item.id === selectedTask);
    if (!task) return;
    if (value === "project" && !task.project_id) setSelectedTask("");
    if (value === "department_work" && !task.department_work_id) {
      setSelectedTask("");
    }
  }

  function changeProject(value: string) {
    setSelectedProject(value);
    const task = tasks.find((item) => item.id === selectedTask);
    if (task && task.project_id !== value) setSelectedTask("");
  }

  function changeDepartmentWork(value: string) {
    setSelectedDepartmentWork(value);
    const task = tasks.find((item) => item.id === selectedTask);
    if (task && task.department_work_id !== value) setSelectedTask("");
  }

  function changeTask(value: string) {
    setSelectedTask(value);
    const task = tasks.find((item) => item.id === value);
    if (!task) return;
    if (task.project_id) {
      setSourceType("project");
      setSelectedProject(task.project_id);
    } else if (task.department_work_id) {
      setSourceType("department_work");
      setSelectedDepartmentWork(task.department_work_id);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const form = new FormData(event.currentTarget);
    const totalHours = Number(form.get("time_hours"));
    if (!totalHours && (record.time_blocks ?? []).length) {
      setError("已移除全部时间块：请重新圈选工作时间块，或取消本次编辑。");
      return;
    }
    const task = tasks.find((item) => item.id === selectedTask);
    let projectId: string | null = null;
    let departmentWorkId: string | null = null;
    if (task) {
      projectId = task.project_id;
      departmentWorkId = task.department_work_id;
    } else if (sourceType === "project") {
      projectId = selectedProject || null;
    } else if (sourceType === "department_work") {
      departmentWorkId = selectedDepartmentWork || null;
    }
    // 未圈选时不携带 time_blocks（后端约定 null = 不改动）并保留原 minutes，
    // 避免把无区间的历史记录误清为空区间。
    const payload: Record<string, unknown> = {
      revision: record.revision,
      work_date: String(form.get("work_date")),
      content: String(form.get("content")),
      minutes: totalHours ? Math.round(totalHours * 60) : record.minutes,
      project_id: projectId,
      department_work_id: departmentWorkId,
      task_id: optional(selectedTask),
      risk: optional(form.get("risk")),
      next_action: optional(form.get("next_action")),
      delegated_edit_reason: delegated
        ? optional(form.get("delegated_edit_reason"))
        : null,
    };
    if (totalHours) {
      payload.time_blocks = JSON.parse(String(form.get("time_blocks") ?? "[]"));
    }
    setSubmitting(true);
    try {
      await api.records.update(record.id, payload);
      onUpdated();
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "工作记录更新失败",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title={`编辑工作记录 · ${record.author_display_name}`}
      eyebrow="EDIT WORK LOG"
      onClose={onClose}
      wide
    >
      <form className="modal-form" onSubmit={submit}>
        <div className="form-grid">
          <label className="field">
            <span>工作日期 *</span>
            <input
              name="work_date"
              type="date"
              defaultValue={record.work_date}
              required
            />
          </label>
          <div className="field field-span-two">
            <span>投入时间（圈选时间块）*</span>
            <div className="tbp-scroll">
              <TimeBlockPicker
                name="time"
                defaultBlocks={record.time_blocks ?? []}
                onChange={(blocks) => setPickedBlocks(blocks)}
              />
            </div>
            {!pickedBlocks.length && record.minutes ? (
              <small className="field-hint">
                本条记录暂无工作区间，当前工时 {formatHours(record.minutes)}
                ；圈选时间块后保存将自动补录区间与工时。
              </small>
            ) : null}
          </div>
          <fieldset className="source-options field-span-two">
            <legend>工作来源</legend>
            <label>
              <input
                type="radio"
                name="source_type"
                checked={sourceType === "project"}
                onChange={() => changeSourceType("project")}
              />
              <span>项目</span>
            </label>
            {showDepartmentWorkSource ? (
              <label>
                <input
                  type="radio"
                  name="source_type"
                  checked={sourceType === "department_work"}
                  onChange={() => changeSourceType("department_work")}
                />
                <span>部门工作</span>
              </label>
            ) : null}
            <label>
              <input
                type="radio"
                name="source_type"
                checked={sourceType === "none"}
                onChange={() => changeSourceType("none")}
              />
              <span>暂不关联</span>
            </label>
          </fieldset>
          {sourceType === "project" ? (
            <label className="field">
              <span>关联项目</span>
              <select
                name="project_id"
                value={selectedProject}
                onChange={(event) => changeProject(event.target.value)}
              >
                <option value="">请选择项目</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {sourceType === "department_work" ? (
            <label className="field">
              <span>关联部门工作</span>
              <select
                name="department_work_id"
                value={selectedDepartmentWork}
                onChange={(event) => changeDepartmentWork(event.target.value)}
              >
                <option value="">请选择部门工作</option>
                {selectedDepartmentWork &&
                !departmentWorks.some(
                  (work) => work.id === selectedDepartmentWork,
                ) ? (
                  <option value={selectedDepartmentWork}>
                    {record.department_work_name ?? "当前部门工作"}
                  </option>
                ) : null}
                {departmentWorks.map((work) => (
                  <option key={work.id} value={work.id}>
                    {work.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label className="field">
            <span>关联任务</span>
            <select
              name="task_id"
              value={selectedTask}
              onChange={(event) => changeTask(event.target.value)}
            >
              <option value="">不关联具体任务</option>
              {visibleTasks.map((task) => (
                <option key={task.id} value={task.id}>
                  {task.title}
                </option>
              ))}
            </select>
          </label>
          <label className="field field-span-two">
            <span>工作内容 *</span>
            <textarea
              name="content"
              rows={5}
              defaultValue={record.content}
              required
              autoFocus
            />
          </label>
          <label className="field">
            <span>风险或阻塞</span>
            <textarea name="risk" rows={3} defaultValue={record.risk ?? ""} />
          </label>
          <label className="field">
            <span>下一步行动</span>
            <textarea
              name="next_action"
              rows={3}
              defaultValue={record.next_action ?? ""}
            />
          </label>
          {delegated ? (
            <label className="field field-span-two">
              <span>代编辑原因 *</span>
              <textarea
                name="delegated_edit_reason"
                rows={3}
                required
                placeholder="说明代为修改他人记录的原因"
              />
            </label>
          ) : null}
        </div>
        {record.deliverables.length ? (
          <InlineNotice>
            已关联的 {record.deliverables.length} 个产出物会保留，并随来源归属同步调整。
          </InlineNotice>
        ) : null}
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" disabled={submitting}>
            {submitting ? "正在保存…" : "保存修改"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function QuickCreateModal({
  projects,
  departmentWorks,
  departments,
  tasks,
  users,
  currentUserId,
  currentUserRole,
  currentDepartmentId,
  canViewProjects,
  canViewDepartmentWorks,
  canCreateProjects,
  canCreateDepartmentWorks,
  canCreateTasks,
  onClose,
  onCreated,
}: {
  projects: ProjectSummary[];
  departmentWorks: DepartmentWork[];
  departments: Department[];
  tasks: Task[];
  users: UserCandidate[];
  currentUserId: string;
  currentUserRole: UserRole;
  currentDepartmentId: string | null;
  canViewProjects: boolean;
  canViewDepartmentWorks: boolean;
  canCreateProjects: boolean;
  canCreateDepartmentWorks: boolean;
  canCreateTasks: boolean;
  onClose: () => void;
  onCreated: (message: string) => void;
}) {
  const [idempotencyKey] = useState(() => createClientMessageId());
  const [sourceType, setSourceType] = useState<QuickSourceType>(
    canViewProjects
      ? "project"
      : canViewDepartmentWorks
        ? "department_work"
        : "none",
  );
  const [selectedProject, setSelectedProject] = useState("");
  const [selectedDepartmentWork, setSelectedDepartmentWork] = useState("");
  const [selectedTask, setSelectedTask] = useState("");
  const [newTaskTitle, setNewTaskTitle] = useState("");
  const [deliverableEnabled, setDeliverableEnabled] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const hasSource = sourceType !== "none";
  // 隐藏超管不能担任负责人（后端 ensure_user 会拒绝）；无主部门用户必须显式选部门
  const isSuperAdmin = currentUserRole === "super_admin";
  const ownerRequired = isSuperAdmin;
  const ownerDefault = isSuperAdmin ? "" : currentUserId;
  const needsDepartmentPick = isSuperAdmin || !currentDepartmentId;
  const visibleTasks = tasks.filter((task) => {
    if (sourceType === "project") {
      return selectedProject ? task.project_id === selectedProject : false;
    }
    if (sourceType === "department_work") {
      return selectedDepartmentWork
        ? task.department_work_id === selectedDepartmentWork
        : false;
    }
    return false;
  });

  function changeSourceType(value: QuickSourceType) {
    setSourceType(value);
    setSelectedTask("");
    if (value === "none") setDeliverableEnabled(false);
  }

  function changeTask(value: string) {
    setSelectedTask(value);
    if (value) setNewTaskTitle("");
  }

  function changeNewTaskTitle(value: string) {
    setNewTaskTitle(value);
    if (value.trim()) setSelectedTask("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setError("");
    const form = new FormData(event.currentTarget);
    const totalHours = Number(form.get("time_hours"));
    if (!totalHours) {
      setError("请先圈选工作时间块（最小 0.5 小时）。");
      return;
    }
    const payload: Record<string, unknown> = {
      idempotency_key: idempotencyKey,
      work_date: String(form.get("work_date")),
      content: String(form.get("content")),
      minutes: Math.round(totalHours * 60),
      time_blocks: JSON.parse(String(form.get("time_blocks") ?? "[]")),
      risk: optional(form.get("risk")),
      next_action: optional(form.get("next_action")),
    };
    if (sourceType === "project") {
      if (!selectedProject) {
        setError("请选择要关联的项目。");
        return;
      }
      payload.project_id = selectedProject;
    } else if (sourceType === "department_work") {
      if (!selectedDepartmentWork) {
        setError("请选择要关联的部门工作。");
        return;
      }
      payload.department_work_id = selectedDepartmentWork;
    } else if (sourceType === "new_project") {
      const newProjectName = String(form.get("new_project_name") ?? "").trim();
      if (!newProjectName) {
        setError("请填写新项目名称。");
        return;
      }
      const ownerId = String(form.get("new_project_owner_id") ?? "");
      if (ownerRequired && !ownerId) {
        setError("超级管理员创建项目时必须指定项目负责人。");
        return;
      }
      payload.new_project = {
        name: newProjectName,
        owner_id: ownerId || undefined,
      };
    } else if (sourceType === "new_department_work") {
      const newWorkName = String(
        form.get("new_department_work_name") ?? "",
      ).trim();
      if (!newWorkName) {
        setError("请填写部门工作名称。");
        return;
      }
      const ownerId = String(form.get("new_department_work_owner_id") ?? "");
      if (ownerRequired && !ownerId) {
        setError("超级管理员创建部门工作时必须指定负责人。");
        return;
      }
      const departmentId = String(
        form.get("new_department_work_department_id") ?? "",
      );
      if (needsDepartmentPick && !departmentId) {
        setError("请选择部门工作所属部门。");
        return;
      }
      payload.new_department_work = {
        name: newWorkName,
        visibility: String(
          form.get("new_department_work_visibility") ?? "department_only",
        ),
        owner_id: ownerId || undefined,
        department_id: departmentId || undefined,
      };
    }
    const taskTitle = newTaskTitle.trim();
    if (hasSource && taskTitle) {
      const ownerId = String(form.get("new_task_owner_id") ?? "");
      if (ownerRequired && !ownerId) {
        setError("超级管理员新建任务时必须指定任务负责人。");
        return;
      }
      payload.new_task = {
        title: taskTitle,
        owner_id: ownerId || undefined,
      };
    } else if (selectedTask) {
      payload.task_id = selectedTask;
    }
    const deliverableName = optional(form.get("deliverable_name"));
    const deliverableUrl = optional(form.get("deliverable_url"));
    if (hasSource && deliverableEnabled && deliverableName && deliverableUrl) {
      payload.deliverables = [{ name: deliverableName, url: deliverableUrl }];
    }
    setSubmitting(true);
    try {
      const result = await api.records.quickCreate(payload);
      if (result.replayed) {
        onCreated("该记录此前已提交成功，已为你恢复原单（未重复创建）。");
        return;
      }
      const created: string[] = [];
      if (result.created_project_id) created.push("项目");
      if (result.created_department_work_id) created.push("部门工作");
      if (result.created_task_id) created.push("任务");
      onCreated(
        created.length
          ? `记录创建成功，已同步新建${created.join("、")}。`
          : "记录创建成功。",
      );
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "快速记录保存失败",
      );
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title="记录工作"
      eyebrow="WORK LOG"
      onClose={onClose}
      wide
    >
      <form className="modal-form" onSubmit={submit}>
        <div className="form-grid">
          <label className="field">
            <span>工作日期 *</span>
            <input
              name="work_date"
              type="date"
              defaultValue={localDateInputValue()}
              required
            />
          </label>
          <div className="field field-span-two">
            <span>投入时间（圈选时间块）*</span>
            <div className="tbp-scroll">
              <TimeBlockPicker name="time" />
            </div>
          </div>
          <fieldset className="source-options field-span-two">
            <legend>工作来源</legend>
            {canViewProjects ? (
              <label>
                <input
                  type="radio"
                  name="source_type"
                  checked={sourceType === "project"}
                  onChange={() => changeSourceType("project")}
                />
                <span>现有项目</span>
              </label>
            ) : null}
            {canViewDepartmentWorks ? (
              <label>
                <input
                  type="radio"
                  name="source_type"
                  checked={sourceType === "department_work"}
                  onChange={() => changeSourceType("department_work")}
                />
                <span>现有部门工作</span>
              </label>
            ) : null}
            {canCreateProjects ? (
              <label>
                <input
                  type="radio"
                  name="source_type"
                  checked={sourceType === "new_project"}
                  onChange={() => changeSourceType("new_project")}
                />
                <span>新建项目</span>
              </label>
            ) : null}
            {canCreateDepartmentWorks ? (
              <label>
                <input
                  type="radio"
                  name="source_type"
                  checked={sourceType === "new_department_work"}
                  onChange={() => changeSourceType("new_department_work")}
                />
                <span>新建部门工作</span>
              </label>
            ) : null}
            <label>
              <input
                type="radio"
                name="source_type"
                checked={sourceType === "none"}
                onChange={() => changeSourceType("none")}
              />
              <span>无来源</span>
            </label>
          </fieldset>
          {sourceType === "project" ? (
            <label className="field">
              <span>关联项目 *</span>
              <select
                name="project_id"
                value={selectedProject}
                onChange={(event) => setSelectedProject(event.target.value)}
              >
                <option value="">请选择项目</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {sourceType === "department_work" ? (
            <label className="field">
              <span>关联部门工作 *</span>
              <select
                name="department_work_id"
                value={selectedDepartmentWork}
                onChange={(event) =>
                  setSelectedDepartmentWork(event.target.value)
                }
              >
                <option value="">请选择部门工作</option>
                {departmentWorks.map((work) => (
                  <option key={work.id} value={work.id}>
                    {work.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {sourceType === "new_project" ? (
            <>
              <label className="field">
                <span>新项目名称 *</span>
                <input
                  name="new_project_name"
                  placeholder="例如 某集团集采平台二期"
                  required
                />
              </label>
              {users.length ? (
                <label className="field">
                  <span>项目负责人{ownerRequired ? " *" : ""}</span>
                  <select
                    name="new_project_owner_id"
                    defaultValue={ownerDefault}
                    required={ownerRequired}
                  >
                    {isSuperAdmin ? (
                      <option value="">请选择负责人</option>
                    ) : null}
                    {users.map((user) => (
                      <option key={user.id} value={user.id}>
                        {user.display_name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
            </>
          ) : null}
          {sourceType === "new_department_work" ? (
            <>
              <label className="field">
                <span>部门工作名称 *</span>
                <input
                  name="new_department_work_name"
                  placeholder="例如 季度巡检与资产盘点"
                  required
                />
              </label>
              {needsDepartmentPick ? (
                <label className="field">
                  <span>所属部门 *</span>
                  <select
                    name="new_department_work_department_id"
                    defaultValue=""
                    required
                  >
                    <option value="">请选择部门</option>
                    {departments.map((department) => (
                      <option key={department.id} value={department.id}>
                        {department.name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <label className="field">
                <span>可见性</span>
                <select
                  name="new_department_work_visibility"
                  defaultValue="department_only"
                >
                  <option value="department_only">仅本部门可见</option>
                  <option value="public">全员公开</option>
                </select>
              </label>
              {users.length ? (
                <label className="field">
                  <span>负责人{ownerRequired ? " *" : ""}</span>
                  <select
                    name="new_department_work_owner_id"
                    defaultValue={ownerDefault}
                    required={ownerRequired}
                  >
                    {isSuperAdmin ? (
                      <option value="">请选择负责人</option>
                    ) : null}
                    {users.map((user) => (
                      <option key={user.id} value={user.id}>
                        {user.display_name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
            </>
          ) : null}
          {sourceType === "project" || sourceType === "department_work" ? (
            <label className="field">
              <span>关联现有任务</span>
              <select
                name="task_id"
                value={selectedTask}
                onChange={(event) => changeTask(event.target.value)}
              >
                <option value="">不关联任务</option>
                {visibleTasks.map((task) => (
                  <option key={task.id} value={task.id}>
                    {task.title}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {hasSource && canCreateTasks ? (
            <>
              <label className="field">
                <span>新建任务标题</span>
                <input
                  name="new_task_title"
                  value={newTaskTitle}
                  onChange={(event) => changeNewTaskTitle(event.target.value)}
                  placeholder="留空则不新建任务"
                />
              </label>
              {users.length && newTaskTitle.trim() ? (
                <label className="field">
                  <span>任务负责人{ownerRequired ? " *" : ""}</span>
                  <select
                    name="new_task_owner_id"
                    defaultValue={ownerDefault}
                    required={ownerRequired}
                  >
                    {isSuperAdmin ? (
                      <option value="">请选择负责人</option>
                    ) : null}
                    {users.map((user) => (
                      <option key={user.id} value={user.id}>
                        {user.display_name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
            </>
          ) : null}
          <label className="field field-span-two">
            <span>工作内容 *</span>
            <textarea
              name="content"
              rows={5}
              placeholder="说明完成了什么、产生了什么结果"
              required
              autoFocus
            />
          </label>
          <label className="field">
            <span>风险或阻塞</span>
            <textarea name="risk" rows={3} placeholder="没有可留空" />
          </label>
          <label className="field">
            <span>下一步行动</span>
            <textarea name="next_action" rows={3} placeholder="下一步准备做什么" />
          </label>
          <div className="field-span-two deliverable-toggle">
            <label className="toggle-filter">
              <input
                type="checkbox"
                checked={deliverableEnabled}
                disabled={!hasSource}
                onChange={(event) => setDeliverableEnabled(event.target.checked)}
              />
              <span />
              添加产出物链接
            </label>
            {!hasSource ? (
              <small className="field-hint">
                产出物必须挂在项目或部门工作上，请先选择或新建来源。
              </small>
            ) : null}
          </div>
          {deliverableEnabled && hasSource ? (
            <>
              <label className="field">
                <span>产出物名称</span>
                <input name="deliverable_name" placeholder="例如 总体方案 V3" />
              </label>
              <label className="field">
                <span>访问地址</span>
                <input
                  name="deliverable_url"
                  type="url"
                  placeholder="https://intranet.example/..."
                />
              </label>
            </>
          ) : null}
        </div>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" disabled={submitting}>
            {submitting ? "正在提交…" : "提交记录"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function groupByDate(records: WorkRecord[]) {
  const groups = new Map<string, WorkRecord[]>();
  records.forEach((record) => {
    groups.set(record.work_date, [
      ...(groups.get(record.work_date) ?? []),
      record,
    ]);
  });
  return Array.from(groups.entries());
}

function humanDate(value: string) {
  const date = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "short",
  }).format(date);
}

function formatHours(minutes: number) {
  const hours = minutes / 60;
  return Number.isInteger(hours) ? `${hours}h` : `${hours.toFixed(1)}h`;
}

/** 当前自然周（周一至周日，Asia/Shanghai）的 YYYY-MM-DD 起止。 */
function currentWeekRange() {
  const shanghaiNow = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Shanghai" }),
  );
  const weekday = shanghaiNow.getDay() || 7;
  const monday = new Date(shanghaiNow);
  monday.setDate(shanghaiNow.getDate() - (weekday - 1));
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  const format = (value: Date) =>
    `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
  return { start: format(monday), end: format(sunday) };
}

function optional(value: FormDataEntryValue | null) {
  const text = String(value ?? "").trim();
  return text || null;
}
