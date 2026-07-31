"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiClientError } from "../api";
import type { ProjectSummary, Task, TaskStatus, User } from "../types";
import { AvatarImage } from "./avatar";
import { Plus } from "./icons";
import { EmptyState, InlineNotice, Modal, StatusBadge } from "./ui";

export function TasksView({ canManage }: { canManage: boolean }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [status, setStatus] = useState("");
  const [projectId, setProjectId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (status) params.set("status", status);
      if (projectId) params.set("project_id", projectId);
      const [taskRows, projectRows, userRows] = await Promise.all([
        api.tasks.list(params),
        api.projects.list(),
        api.users.list(),
      ]);
      setTasks(taskRows);
      setProjects(projectRows);
      setUsers(userRows);
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "任务数据加载失败",
      );
    } finally {
      setLoading(false);
    }
  }, [projectId, status]);

  useEffect(() => {
    const timeout = window.setTimeout(load, 0);
    return () => window.clearTimeout(timeout);
  }, [load]);

  const projectNames = useMemo(
    () => new Map(projects.map((project) => [project.id, project.name])),
    [projects],
  );
  const userNames = useMemo(
    () => new Map(users.map((user) => [user.id, user.display_name])),
    [users],
  );

  async function transition(task: Task, target: TaskStatus) {
    const payload: {
      revision: number;
      status: string;
      blocker_reason?: string;
      result?: string;
      cancel_reason?: string;
    } = { revision: task.revision, status: target };
    if (target === "blocked") {
      const reason = window.prompt("请填写阻塞原因");
      if (!reason) return;
      payload.blocker_reason = reason;
    }
    if (target === "done") {
      const result = window.prompt("请填写任务完成结果");
      if (!result) return;
      payload.result = result;
    }
    if (target === "cancelled") {
      const reason = window.prompt("请填写取消原因");
      if (!reason) return;
      payload.cancel_reason = reason;
    }
    try {
      await api.tasks.transition(task.id, payload);
      await load();
    } catch (caught) {
      setError(caught instanceof ApiClientError ? caught.message : "状态更新失败");
    }
  }

  return (
    <div className="view-shell">
      <header className="view-header">
        <div>
          <p className="eyebrow">DELIVERY FLOW</p>
          <h1>任务</h1>
          <p>围绕项目组织可执行事项，清楚记录负责人、阻塞与完成结果。</p>
        </div>
        {canManage ? (
          <button className="primary-button" onClick={() => setCreateOpen(true)}>
            <Plus size={14} /> 新建任务
          </button>
        ) : null}
      </header>

      <section className="toolbar">
        <label className="select-filter select-wide">
          <span>所属项目</span>
          <select
            value={projectId}
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
        <div className="segmented-filter" aria-label="任务状态筛选">
          {[
            ["", "全部"],
            ["todo", "待开始"],
            ["in_progress", "处理中"],
            ["blocked", "阻塞"],
            ["done", "已完成"],
          ].map(([value, label]) => (
            <button
              key={value}
              className={status === value ? "active" : ""}
              onClick={() => setStatus(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="toolbar-meta">
          <strong>{tasks.length}</strong>
          <span>项任务</span>
        </div>
      </section>

      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
      <section className="task-board">
        {loading ? (
          <div className="list-loading">
            <i />
            <span>正在载入任务…</span>
          </div>
        ) : tasks.length ? (
          tasks.map((task) => (
            <article className="task-card" key={task.id}>
              <div className={`priority-rail priority-${task.priority}`} />
              <header>
                <span className={`priority-label priority-${task.priority}`}>
                  {task.priority.toUpperCase()}
                </span>
                <StatusBadge status={task.status} />
              </header>
              <h3>{task.title}</h3>
              <p>{task.description || "暂未填写任务说明。"}</p>
              <dl>
                <div>
                  <dt>项目</dt>
                  <dd>{projectNames.get(task.project_id) ?? "未知项目"}</dd>
                </div>
                <div>
                  <dt>负责人</dt>
                  <dd>{userNames.get(task.owner_id) ?? "未知用户"}</dd>
                </div>
                <div>
                  <dt>截止日期</dt>
                  <dd>{task.due_date ?? "未设置"}</dd>
                </div>
              </dl>
              {task.blocker_reason ? (
                <div className="blocker-note">阻塞：{task.blocker_reason}</div>
              ) : null}
              <footer>
                {canManage
                  ? nextTaskActions(task.status).map((action) => (
                      <button
                        key={action.status}
                        className={
                          action.primary ? "small-primary" : "text-button"
                        }
                        onClick={() => transition(task, action.status)}
                      >
                        {action.label}
                      </button>
                    ))
                  : null}
              </footer>
            </article>
          ))
        ) : (
          <div className="board-empty">
            <EmptyState
              title="当前没有任务"
              description="创建任务，让项目推进有明确的责任与结果。"
            />
          </div>
        )}
      </section>

      {createOpen && canManage ? (
        <TaskCreateModal
          projects={projects}
          users={users}
          onClose={() => setCreateOpen(false)}
          onCreated={async () => {
            setCreateOpen(false);
            await load();
          }}
        />
      ) : null}
    </div>
  );
}

function TaskCreateModal({
  projects,
  users,
  onClose,
  onCreated,
}: {
  projects: ProjectSummary[];
  users: User[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      await api.tasks.create({
        project_id: String(form.get("project_id")),
        title: String(form.get("title")),
        description: optional(form.get("description")),
        owner_id: String(form.get("owner_id")),
        priority: String(form.get("priority")),
        due_date: optional(form.get("due_date")),
        collaborator_ids: form.getAll("collaborator_ids").map(String),
      });
      onCreated();
    } catch (caught) {
      setError(caught instanceof ApiClientError ? caught.message : "任务创建失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title="创建可执行任务" eyebrow="NEW TASK" onClose={onClose} wide>
      <form className="modal-form" onSubmit={submit}>
        <div className="form-grid">
          <label className="field field-span-two">
            <span>任务标题 *</span>
            <input name="title" placeholder="清晰描述需要完成的事项" required autoFocus />
          </label>
          <label className="field">
            <span>所属项目 *</span>
            <select name="project_id" required defaultValue="">
              <option value="" disabled>
                选择项目
              </option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>负责人 *</span>
            <select name="owner_id" required defaultValue="">
              <option value="" disabled>
                选择负责人
              </option>
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.display_name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>优先级</span>
            <select name="priority" defaultValue="p1">
              <option value="p0">P0 · 紧急</option>
              <option value="p1">P1 · 正常</option>
              <option value="p2">P2 · 较低</option>
            </select>
          </label>
          <label className="field">
            <span>截止日期</span>
            <input name="due_date" type="date" />
          </label>
          <label className="field field-span-two">
            <span>任务说明</span>
            <textarea name="description" rows={4} placeholder="补充范围、标准或背景" />
          </label>
          <fieldset className="people-options field-span-two">
            <legend>协作成员</legend>
            {users.map((user) => (
              <label key={user.id}>
                <input
                  type="checkbox"
                  name="collaborator_ids"
                  value={user.id}
                />
                <AvatarImage
                  avatarKey={user.avatar_key}
                  displayName={user.display_name}
                  decorative
                />
                <strong>{user.display_name}</strong>
              </label>
            ))}
          </fieldset>
        </div>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" disabled={submitting}>
            {submitting ? "正在创建…" : "创建任务"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function nextTaskActions(status: TaskStatus) {
  if (status === "todo") {
    return [
      { status: "in_progress" as const, label: "开始处理", primary: true },
      { status: "blocked" as const, label: "标记阻塞" },
      { status: "cancelled" as const, label: "取消" },
    ];
  }
  if (status === "in_progress") {
    return [
      { status: "done" as const, label: "完成任务", primary: true },
      { status: "blocked" as const, label: "标记阻塞" },
      { status: "cancelled" as const, label: "取消" },
    ];
  }
  if (status === "blocked") {
    return [
      { status: "in_progress" as const, label: "解除阻塞", primary: true },
      { status: "cancelled" as const, label: "取消" },
    ];
  }
  return [];
}

function optional(value: FormDataEntryValue | null) {
  const text = String(value ?? "").trim();
  return text || null;
}
