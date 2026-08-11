"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { api, apiErrorMessage, ApiClientError } from "../api";
import { canManageTaskObject } from "../object-permissions";
import { pinyinMatchAny } from "../pinyin";
import type {
  DepartmentWork,
  ProjectSummary,
  Task,
  TaskProgressHistory,
  TaskStatus,
  TaskTimeScope,
  User,
  UserCandidate,
} from "../types";
import { AvatarImage } from "./avatar";
import { Plus, Search } from "./icons";
import { EmptyState, InlineNotice, Modal, StatusBadge } from "./ui";
import {
  TaskDetailModal,
  TaskGroupDetail,
  TaskGroupOverview,
  type TaskGroup,
} from "./task-canvas";

const TERMINAL_STATUSES: ReadonlySet<TaskStatus> = new Set([
  "done",
  "cancelled",
]);

type TimeBucket = "overdue" | "due" | "future" | "none";

/** 当前「今天 / 本周日」日期（Asia/Shanghai，YYYY-MM-DD）。 */
function shanghaiWeekWindow() {
  const shanghaiNow = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Shanghai" }),
  );
  const format = (value: Date) =>
    `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
  const weekday = shanghaiNow.getDay() || 7;
  const sunday = new Date(shanghaiNow);
  sunday.setDate(shanghaiNow.getDate() + (7 - weekday));
  return { today: format(shanghaiNow), weekEnd: format(sunday) };
}

function taskTimeBucket(
  task: Task,
  scope: "today" | "week",
  today: string,
  weekEnd: string,
): TimeBucket {
  if (!task.due_date) return "none";
  if (task.due_date < today) return "overdue";
  if (scope === "today") return task.due_date === today ? "due" : "future";
  return task.due_date <= weekEnd ? "due" : "future";
}

const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  todo: "待开始",
  in_progress: "处理中",
  blocked: "阻塞",
  done: "已完成",
  cancelled: "已取消",
};

export function TasksView({
  canEdit,
  canCreate,
  currentUser,
}: {
  canEdit: boolean;
  canCreate: boolean;
  currentUser: User;
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [departmentWorks, setDepartmentWorks] = useState<DepartmentWork[]>([]);
  const [users, setUsers] = useState<UserCandidate[]>([]);
  const [timeScope, setTimeScope] = useState<TaskTimeScope>("week");
  const [status, setStatus] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [boardMode, setBoardMode] = useState<"overview" | "board">("overview");
  const [openGroupKey, setOpenGroupKey] = useState<string | null>(null);
  const [detailTaskId, setDetailTaskId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createParent, setCreateParent] = useState<Task | null>(null);
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [reassigningTask, setReassigningTask] = useState<Task | null>(null);
  const [transitionRequest, setTransitionRequest] = useState<{
    task: Task;
    target: TaskStatus;
  } | null>(null);
  const [progressTask, setProgressTask] = useState<Task | null>(null);
  const [historyTask, setHistoryTask] = useState<Task | null>(null);
  const [deletingTask, setDeletingTask] = useState<Task | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      params.set("time_scope", "all");
      if (status) params.set("status", status);
      const [taskRows, projectRows, workRows, userRows] = await Promise.all([
        api.tasks.list(params),
        api.projects.list(),
        api.departmentWorks.list(),
        api.users.candidates(),
      ]);
      setTasks(taskRows);
      setProjects(projectRows);
      setDepartmentWorks(
        workRows.filter((work) => work.status !== "archived"),
      );
      setUsers(userRows);
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "任务数据加载失败",
      );
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    const timeout = window.setTimeout(load, 0);
    return () => window.clearTimeout(timeout);
  }, [load]);

  const projectNames = useMemo(
    () => new Map(projects.map((project) => [project.id, project.name])),
    [projects],
  );
  const projectOwners = useMemo(
    () => new Map(projects.map((project) => [project.id, project.owner_id])),
    [projects],
  );
  const workNames = useMemo(
    () => new Map(departmentWorks.map((work) => [work.id, work.name])),
    [departmentWorks],
  );
  const workOwners = useMemo(
    () => new Map(departmentWorks.map((work) => [work.id, work.owner_id])),
    [departmentWorks],
  );
  const userNames = useMemo(
    () => new Map(users.map((user) => [user.id, user.display_name])),
    [users],
  );
  const childrenByParent = useMemo(() => {
    const map = new Map<string, Task[]>();
    tasks.forEach((task) => {
      if (task.parent_id) {
        map.set(task.parent_id, [...(map.get(task.parent_id) ?? []), task]);
      }
    });
    return map;
  }, [tasks]);

  const visibleTasks = useMemo(
    () =>
      tasks.filter((task) => {
        if (sourceFilter) {
          const separator = sourceFilter.indexOf(":");
          const kind = sourceFilter.slice(0, separator);
          const id = sourceFilter.slice(separator + 1);
          if (kind === "project" && task.project_id !== id) return false;
          if (kind === "work" && task.department_work_id !== id) return false;
        }
        return pinyinMatchAny(
          [
            task.title,
            userNames.get(task.owner_id),
            ...task.collaborator_ids.map((id) => userNames.get(id)),
          ],
          search,
        );
      }),
    [tasks, sourceFilter, search, userNames],
  );

  const taskGroups = useMemo<TaskGroup[]>(() => {
    const groups = new Map<string, TaskGroup>();
    for (const task of visibleTasks) {
      const kind = task.project_id ? "project" : "work";
      const id = task.project_id ?? task.department_work_id ?? "ungrouped";
      const key = `${kind}:${id}`;
      let group = groups.get(key);
      if (!group) {
        group = {
          key,
          kind,
          id,
          name:
            kind === "project"
              ? (projectNames.get(id) ?? "未知项目")
              : id === "ungrouped"
                ? "未分组"
                : (workNames.get(id) ?? "未知部门工作"),
          tasks: [],
        };
        groups.set(key, group);
      }
      group.tasks.push(task);
    }
    return [...groups.values()].sort(
      (a, b) => b.tasks.length - a.tasks.length,
    );
  }, [visibleTasks, projectNames, workNames]);

  const openGroup = taskGroups.find((group) => group.key === openGroupKey) ?? null;
  const detailTask = detailTaskId
    ? (tasks.find((task) => task.id === detailTaskId) ?? null)
    : null;

  // 时间筛选分桶：仅「今天/本周」生效；全部模式为 null
  const activeScope: "today" | "week" | null =
    timeScope === "all" ? null : timeScope;
  const bucketWindow = shanghaiWeekWindow();
  const timeBuckets = useMemo<Record<TimeBucket, Task[]> | null>(() => {
    if (!activeScope) return null;
    const buckets: Record<TimeBucket, Task[]> = {
      overdue: [],
      due: [],
      future: [],
      none: [],
    };
    for (const task of visibleTasks) {
      buckets[
        taskTimeBucket(
          task,
          activeScope,
          bucketWindow.today,
          bucketWindow.weekEnd,
        )
      ].push(task);
    }
    return buckets;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleTasks, activeScope]);

  const groupBuckets = useMemo<Record<TimeBucket, TaskGroup[]> | null>(() => {
    if (!timeBuckets || !activeScope) return null;
    const rank: Record<TimeBucket, number> = {
      overdue: 0,
      due: 1,
      future: 2,
      none: 3,
    };
    const buckets: Record<TimeBucket, TaskGroup[]> = {
      overdue: [],
      due: [],
      future: [],
      none: [],
    };
    for (const group of taskGroups) {
      let bucket: TimeBucket = "none";
      for (const task of group.tasks) {
        const own = taskTimeBucket(
          task,
          activeScope,
          bucketWindow.today,
          bucketWindow.weekEnd,
        );
        if (rank[own] < rank[bucket]) bucket = own;
      }
      buckets[bucket].push(group);
    }
    return buckets;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskGroups, timeBuckets, activeScope]);

  const dueSectionLabel = timeScope === "today" ? "今日待完成" : "本周待完成";
  const dueEmptyHint =
    timeScope === "today"
      ? "今天没有待完成的任务，可以处理逾期或规划后续安排"
      : "本周没有待完成的任务，可以处理逾期或规划后续安排";

  function collectDescendants(taskId: string) {
    const collected: Task[] = [];
    const queue: string[] = [taskId];
    let current = queue.pop();
    while (current !== undefined) {
      const children = childrenByParent.get(current) ?? [];
      children.forEach((child) => {
        collected.push(child);
        queue.push(child.id);
      });
      current = queue.pop();
    }
    return collected;
  }

  function requestTransition(task: Task, target: TaskStatus) {
    if (target === "in_progress") {
      void runTransition(task, target);
      return;
    }
    setTransitionRequest({ task, target });
  }

  async function runTransition(task: Task, target: TaskStatus) {
    setError("");
    try {
      await api.tasks.transition(task.id, {
        revision: task.revision,
        status: target,
      });
      await load();
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "状态更新失败",
      );
    }
  }

  function renderDivider(
    label: string,
    options?: { danger?: boolean; hint?: string },
  ) {
    return (
      <div className="task-filter-divider" key={`divider-${label}`}>
        {options?.hint ? <p>{options.hint}</p> : null}
        <div
          className={`task-filter-divider-line${options?.danger ? " danger" : ""}`}
        >
          <span>{label}</span>
        </div>
      </div>
    );
  }

  function renderTaskCard(task: Task) {
    const terminal = TERMINAL_STATUSES.has(task.status);
    return (
      <article className="task-card" key={task.id}>
        <div className={`priority-rail priority-${task.priority}`} />
        <header>
          <span className="task-card-badges">
            <span className={`priority-label priority-${task.priority}`}>
              {task.priority.toUpperCase()}
            </span>
            {task.level > 0 ? (
              <span className="task-level-tag">L{task.level + 1} 子任务</span>
            ) : null}
          </span>
          <StatusBadge status={task.status} />
        </header>
        <h3>{task.title}</h3>
        <p>{task.description || "暂未填写任务说明。"}</p>
        <dl>
          <div>
            <dt>来源</dt>
            <dd>
              <span
                className={`source-tag ${
                  task.project_id ? "source-project" : "source-work"
                }`}
              >
                {task.project_id ? "项目" : "部门工作"}
              </span>
              {taskSourceName(task, projectNames, workNames)}
            </dd>
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
        {task.progress_enabled ? (
          <div className="task-progress">
            <div className="task-progress-track">
              <div
                className="task-progress-fill"
                style={{ width: `${task.progress_percent ?? 0}%` }}
              />
            </div>
            <span className="task-progress-value">
              {task.progress_percent ?? 0}%
            </span>
          </div>
        ) : null}
        {task.blocker_reason ? (
          <div className="blocker-note">阻塞：{task.blocker_reason}</div>
        ) : null}
        <footer>
          {canManageTaskObject(
            canEdit,
            currentUser,
            task,
            task.project_id
              ? projectOwners.get(task.project_id)
              : workOwners.get(task.department_work_id ?? ""),
          )
            ? (
              <>
                <button
                  className="text-button"
                  onClick={() => setEditingTask(task)}
                >
                  编辑
                </button>
                <button
                  className="text-button"
                  onClick={() => setReassigningTask(task)}
                >
                  转派
                </button>
                {nextTaskActions(task.status).map((action) => (
                  <button
                    key={action.status}
                    className={action.primary ? "small-primary" : "text-button"}
                    onClick={() => requestTransition(task, action.status)}
                  >
                    {action.label}
                  </button>
                ))}
                {!terminal ? (
                  <button
                    className="text-button"
                    onClick={() => setProgressTask(task)}
                  >
                    更新进度
                  </button>
                ) : null}
                {task.progress_enabled ? (
                  <button
                    className="text-button"
                    onClick={() => setHistoryTask(task)}
                  >
                    进度历史
                  </button>
                ) : null}
                {canCreate && task.level < 2 && !terminal ? (
                  <button
                    className="text-button"
                    onClick={() => {
                      setCreateParent(task);
                      setCreateOpen(true);
                    }}
                  >
                    新建子任务
                  </button>
                ) : null}
                <button
                  className="text-button"
                  style={{ color: "var(--red)" }}
                  onClick={() => setDeletingTask(task)}
                >
                  删除
                </button>
              </>
            )
            : null}
        </footer>
      </article>
    );
  }

  return (
    <div className="view-shell">
      <header className="view-header">
        <div>
          <p className="eyebrow">DELIVERY FLOW</p>
          <h1>任务</h1>
          <p>围绕项目与部门工作组织可执行事项，清楚记录负责人、阻塞与完成结果。</p>
        </div>
        {canCreate ? (
          <button
            className="primary-button"
            onClick={() => {
              setCreateParent(null);
              setCreateOpen(true);
            }}
          >
            <Plus size={14} /> 新建任务
          </button>
        ) : null}
      </header>

      {boardMode === "board" || !openGroup ? (
        <section className="toolbar">
          <div className="segmented-filter" aria-label="显示模式">
            <button
              className={boardMode === "overview" ? "active" : ""}
              onClick={() => setBoardMode("overview")}
            >
              总览
            </button>
            <button
              className={boardMode === "board" ? "active" : ""}
              onClick={() => setBoardMode("board")}
            >
              看板
            </button>
          </div>
          <div className="segmented-filter" aria-label="时间范围筛选">
          {(
            [
              ["today", "今天"],
              ["week", "本周"],
              ["all", "全部"],
            ] as Array<[TaskTimeScope, string]>
          ).map(([value, label]) => (
            <button
              key={value}
              className={timeScope === value ? "active" : ""}
              onClick={() => setTimeScope(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="select-filter select-wide">
          <span>来源</span>
          <select
            value={sourceFilter}
            onChange={(event) => setSourceFilter(event.target.value)}
          >
            <option value="">全部来源</option>
            <optgroup label="项目">
              {projects.map((project) => (
                <option key={project.id} value={`project:${project.id}`}>
                  {project.name}
                </option>
              ))}
            </optgroup>
            <optgroup label="部门工作">
              {departmentWorks.map((work) => (
                <option key={work.id} value={`work:${work.id}`}>
                  {work.name}
                </option>
              ))}
            </optgroup>
          </select>
        </label>
        <label className="select-filter">
          <span>状态</span>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="">全部状态</option>
            <option value="todo">待开始</option>
            <option value="in_progress">处理中</option>
            <option value="blocked">阻塞</option>
            <option value="done">已完成</option>
            <option value="cancelled">已取消</option>
          </select>
        </label>
        <label className="search-box">
          <span aria-hidden="true">
            <Search size={16} />
          </span>
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索任务或参与人"
          />
        </label>
        <div className="toolbar-meta">
          <strong>{visibleTasks.length}</strong>
          <span>项任务</span>
        </div>
      </section>
      ) : null}

      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}

      {boardMode === "overview" ? (
        loading ? (
          <div className="list-loading">
            <i />
            <span>正在载入任务…</span>
          </div>
        ) : openGroup ? (
          <TaskGroupDetail
            key={openGroup.key}
            group={openGroup}
            userNames={userNames}
            onBack={() => setOpenGroupKey(null)}
            onOpenTask={(task) => setDetailTaskId(task.id)}
          />
        ) : taskGroups.length ? (
          groupBuckets ? (
            <>
              {groupBuckets.overdue.length ? (
                <>
                  {renderDivider("已逾期", { danger: true })}
                  <TaskGroupOverview
                    groups={groupBuckets.overdue}
                    onOpenGroup={(group) => setOpenGroupKey(group.key)}
                  />
                </>
              ) : null}
              {renderDivider(dueSectionLabel, {
                hint:
                  groupBuckets.due.length === 0 ? dueEmptyHint : undefined,
              })}
              {groupBuckets.due.length ? (
                <TaskGroupOverview
                  groups={groupBuckets.due}
                  onOpenGroup={(group) => setOpenGroupKey(group.key)}
                />
              ) : null}
              {groupBuckets.future.length ? (
                <>
                  {renderDivider("更晚到期")}
                  <TaskGroupOverview
                    groups={groupBuckets.future}
                    onOpenGroup={(group) => setOpenGroupKey(group.key)}
                  />
                </>
              ) : null}
              {groupBuckets.none.length ? (
                <>
                  {renderDivider("未设置截止日期")}
                  <TaskGroupOverview
                    groups={groupBuckets.none}
                    onOpenGroup={(group) => setOpenGroupKey(group.key)}
                  />
                </>
              ) : null}
            </>
          ) : (
            <TaskGroupOverview
              groups={taskGroups}
              onOpenGroup={(group) => setOpenGroupKey(group.key)}
            />
          )
        ) : (
          <div className="board-empty">
            <EmptyState
              title="当前没有任务"
              description="调整筛选条件，或创建任务，让推进有明确的责任与结果。"
            />
          </div>
        )
      ) : (
      <section className="task-board">
        {loading ? (
          <div className="list-loading">
            <i />
            <span>正在载入任务…</span>
          </div>
        ) : visibleTasks.length ? (
          timeBuckets ? (
            <>
              {timeBuckets.overdue.length ? (
                <>
                  {renderDivider("已逾期", { danger: true })}
                  {timeBuckets.overdue.map(renderTaskCard)}
                </>
              ) : null}
              {renderDivider(dueSectionLabel, {
                hint:
                  timeBuckets.due.length === 0 ? dueEmptyHint : undefined,
              })}
              {timeBuckets.due.map(renderTaskCard)}
              {timeBuckets.future.length ? (
                <>
                  {renderDivider("更晚到期")}
                  {timeBuckets.future.map(renderTaskCard)}
                </>
              ) : null}
              {timeBuckets.none.length ? (
                <>
                  {renderDivider("未设置截止日期")}
                  {timeBuckets.none.map(renderTaskCard)}
                </>
              ) : null}
            </>
          ) : (
            visibleTasks.map(renderTaskCard)
          )
        ) : (
          <div className="board-empty">
            <EmptyState
              title="当前没有任务"
              description="调整筛选条件，或创建任务，让推进有明确的责任与结果。"
            />
          </div>
        )}
      </section>
      )}

      {detailTask ? (
        <TaskDetailModal
          task={detailTask}
          sourceName={taskSourceName(detailTask, projectNames, workNames)}
          childTasks={childrenByParent.get(detailTask.id) ?? []}
          userNames={userNames}
          users={users}
          canManage={canManageTaskObject(
            canEdit,
            currentUser,
            detailTask,
            detailTask.project_id
              ? projectOwners.get(detailTask.project_id)
              : workOwners.get(detailTask.department_work_id ?? ""),
          )}
          canCreate={canCreate}
          transitionActions={nextTaskActions(detailTask.status)}
          onClose={() => setDetailTaskId(null)}
          onEdit={() => {
            setDetailTaskId(null);
            setEditingTask(detailTask);
          }}
          onReassign={() => {
            setDetailTaskId(null);
            setReassigningTask(detailTask);
          }}
          onTransition={(target) => {
            setDetailTaskId(null);
            requestTransition(detailTask, target);
          }}
          onProgress={() => {
            setDetailTaskId(null);
            setProgressTask(detailTask);
          }}
          onHistory={() => {
            setDetailTaskId(null);
            setHistoryTask(detailTask);
          }}
          onNewSubtask={() => {
            setDetailTaskId(null);
            setCreateParent(detailTask);
            setCreateOpen(true);
          }}
          onDelete={() => {
            setDetailTaskId(null);
            setDeletingTask(detailTask);
          }}
        />
      ) : null}

      {createOpen && canCreate ? (
        <TaskCreateModal
          projects={projects}
          departmentWorks={departmentWorks}
          users={users}
          parent={createParent}
          onClose={() => setCreateOpen(false)}
          onCreated={async () => {
            setCreateOpen(false);
            setCreateParent(null);
            await load();
          }}
        />
      ) : null}

      {editingTask ? (
        <TaskEditModal
          task={editingTask}
          users={users}
          onClose={() => setEditingTask(null)}
          onSaved={async () => {
            setEditingTask(null);
            await load();
          }}
        />
      ) : null}

      {reassigningTask ? (
        <TaskReassignModal
          task={reassigningTask}
          users={users}
          onClose={() => setReassigningTask(null)}
          onSaved={async () => {
            setReassigningTask(null);
            await load();
          }}
        />
      ) : null}

      {transitionRequest ? (
        <TaskTransitionModal
          task={transitionRequest.task}
          target={transitionRequest.target}
          hasIncompleteDescendants={collectDescendants(
            transitionRequest.task.id,
          ).some((item) => !TERMINAL_STATUSES.has(item.status))}
          onClose={() => setTransitionRequest(null)}
          onSaved={async () => {
            setTransitionRequest(null);
            await load();
          }}
        />
      ) : null}

      {progressTask ? (
        <TaskProgressModal
          task={progressTask}
          onClose={() => setProgressTask(null)}
          onSaved={async () => {
            setProgressTask(null);
            await load();
          }}
        />
      ) : null}

      {historyTask ? (
        <TaskProgressHistoryModal
          task={historyTask}
          userNames={userNames}
          onClose={() => setHistoryTask(null)}
        />
      ) : null}

      {deletingTask ? (
        <TaskDeleteModal
          task={deletingTask}
          descendantCount={collectDescendants(deletingTask.id).length}
          onClose={() => setDeletingTask(null)}
          onDeleted={async () => {
            setDeletingTask(null);
            await load();
          }}
        />
      ) : null}
    </div>
  );
}

function TaskCreateModal({
  projects,
  departmentWorks,
  users,
  parent,
  onClose,
  onCreated,
}: {
  projects: ProjectSummary[];
  departmentWorks: DepartmentWork[];
  users: UserCandidate[];
  parent: Task | null;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [sourceKind, setSourceKind] = useState<"project" | "work">("project");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const payload: Record<string, unknown> = {
      title: String(form.get("title")),
      description: optional(form.get("description")),
      owner_id: String(form.get("owner_id")),
      priority: String(form.get("priority")),
      due_date: optional(form.get("due_date")),
      collaborator_ids: form.getAll("collaborator_ids").map(String),
    };
    if (parent) {
      payload.parent_id = parent.id;
    } else if (sourceKind === "project") {
      payload.project_id = String(form.get("project_id"));
    } else {
      payload.department_work_id = String(form.get("department_work_id"));
    }
    try {
      await api.tasks.create(payload);
      onCreated();
    } catch (caught) {
      setError(caught instanceof ApiClientError ? caught.message : "任务创建失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title={parent ? "创建子任务" : "创建可执行任务"}
      eyebrow="NEW TASK"
      onClose={onClose}
      wide
    >
      <form className="modal-form" onSubmit={submit}>
        <div className="form-grid">
          <label className="field field-span-two">
            <span>任务标题 *</span>
            <input name="title" placeholder="清晰描述需要完成的事项" required autoFocus />
          </label>
          {parent ? (
            <div className="field-span-two">
              <InlineNotice>
                父任务：{parent.title}（子任务自动继承父任务来源，层级最多三级）
              </InlineNotice>
            </div>
          ) : (
            <>
              <div className="field field-span-two">
                <span>来源类型 *</span>
                <div className="segmented-filter">
                  <button
                    type="button"
                    className={sourceKind === "project" ? "active" : ""}
                    onClick={() => setSourceKind("project")}
                  >
                    项目
                  </button>
                  <button
                    type="button"
                    className={sourceKind === "work" ? "active" : ""}
                    onClick={() => setSourceKind("work")}
                  >
                    部门工作
                  </button>
                </div>
              </div>
              {sourceKind === "project" ? (
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
              ) : (
                <label className="field">
                  <span>所属部门工作 *</span>
                  <select name="department_work_id" required defaultValue="">
                    <option value="" disabled>
                      选择部门工作
                    </option>
                    {departmentWorks.map((work) => (
                      <option key={work.id} value={work.id}>
                        {work.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </>
          )}
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

const TRANSITION_FIELD_CONFIG: Partial<
  Record<
    TaskStatus,
    {
      name: "blocker_reason" | "result" | "cancel_reason";
      label: string;
      title: string;
      placeholder: string;
    }
  >
> = {
  blocked: {
    name: "blocker_reason",
    label: "阻塞原因",
    title: "标记阻塞",
    placeholder: "说明当前阻塞点、影响范围与需要的支持",
  },
  done: {
    name: "result",
    label: "完成结果",
    title: "完成任务",
    placeholder: "说明交付内容、结论或验收结果",
  },
  cancelled: {
    name: "cancel_reason",
    label: "取消原因",
    title: "取消任务",
    placeholder: "说明取消该任务的原因",
  },
};

function TaskTransitionModal({
  task,
  target,
  hasIncompleteDescendants,
  onClose,
  onSaved,
}: {
  task: Task;
  target: TaskStatus;
  hasIncompleteDescendants: boolean;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const field = TRANSITION_FIELD_CONFIG[target];
  const [completeDescendants, setCompleteDescendants] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!field) return;
    const form = new FormData(event.currentTarget);
    const text = String(form.get(field.name) ?? "").trim();
    if (!text) {
      setError(`请填写${field.label}。`);
      return;
    }
    setSubmitting(true);
    setError("");
    const payload: {
      revision: number;
      status: string;
      blocker_reason?: string;
      result?: string;
      cancel_reason?: string;
      complete_descendants?: boolean;
    } = { revision: task.revision, status: target };
    if (field.name === "blocker_reason") payload.blocker_reason = text;
    if (field.name === "result") payload.result = text;
    if (field.name === "cancel_reason") payload.cancel_reason = text;
    if (target === "done" && completeDescendants) {
      payload.complete_descendants = true;
    }
    try {
      await api.tasks.transition(task.id, payload);
      await onSaved();
    } catch (caught) {
      setError(apiErrorMessage(caught, "状态更新失败，请稍后重试。"));
    } finally {
      setSubmitting(false);
    }
  }

  if (!field) return null;

  return (
    <Modal
      title={`${field.title} · ${task.title}`}
      eyebrow="TASK TRANSITION"
      onClose={onClose}
    >
      <form className="modal-form" onSubmit={submit}>
        <label className="field">
          <span>{field.label} *</span>
          <textarea
            name={field.name}
            rows={4}
            placeholder={field.placeholder}
            required
            autoFocus
          />
        </label>
        {target === "done" && hasIncompleteDescendants ? (
          <label className="toggle-filter">
            <input
              type="checkbox"
              checked={completeDescendants}
              onChange={(event) => setCompleteDescendants(event.target.checked)}
            />
            <span />
            同步完成全部子任务
          </label>
        ) : null}
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" disabled={submitting}>
            {submitting ? "正在提交…" : `确认${field.title}`}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function TaskProgressModal({
  task,
  onClose,
  onSaved,
}: {
  task: Task;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [enabled, setEnabled] = useState(task.progress_enabled);
  const [percent, setPercent] = useState(task.progress_percent ?? 0);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const result = optional(form.get("result"));
    const reason = optional(form.get("reason"));
    if (enabled && percent === 100 && !result) {
      setError("进度达到 100% 时请填写完成结果。");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await api.tasks.updateProgress(task.id, {
        revision: task.revision,
        enabled,
        percent: enabled ? percent : null,
        result: enabled ? result : null,
        reason: enabled ? reason : null,
      });
      await onSaved();
    } catch (caught) {
      setError(apiErrorMessage(caught, "进度更新失败，请稍后重试。"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title={`更新进度 · ${task.title}`}
      eyebrow="TASK PROGRESS"
      onClose={onClose}
    >
      <form className="modal-form" onSubmit={submit}>
        <label className="toggle-filter">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
          />
          <span />
          开启进度跟踪
        </label>
        {enabled ? (
          <>
            <label className="field">
              <span>当前进度：{percent}%</span>
              <input
                className="progress-range"
                type="range"
                min="0"
                max="100"
                step="5"
                value={percent}
                onChange={(event) => setPercent(Number(event.target.value))}
              />
            </label>
            <label className="field">
              <span>完成结果{percent === 100 ? " *" : ""}</span>
              <textarea
                name="result"
                rows={3}
                defaultValue={task.result ?? ""}
                placeholder={
                  percent === 100
                    ? "进度 100% 时必填，说明交付内容或结论"
                    : "进度达到 100% 时必填，可提前填写"
                }
              />
            </label>
            <label className="field">
              <span>备注</span>
              <textarea
                name="reason"
                rows={2}
                placeholder="补充本次进度调整的说明（可选）"
              />
            </label>
          </>
        ) : (
          <InlineNotice>关闭后将不再跟踪该任务进度，已记录的进度历史会保留。</InlineNotice>
        )}
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" disabled={submitting}>
            {submitting ? "正在保存…" : "保存进度"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function TaskProgressHistoryModal({
  task,
  userNames,
  onClose,
}: {
  task: Task;
  userNames: Map<string, string>;
  onClose: () => void;
}) {
  const [history, setHistory] = useState<TaskProgressHistory[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api.tasks
      .progressHistory(task.id)
      .then((rows) => {
        if (!cancelled) setHistory(rows);
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(
            caught instanceof ApiClientError
              ? caught.message
              : "进度历史加载失败",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [task.id]);

  return (
    <Modal
      title={`进度历史 · ${task.title}`}
      eyebrow="PROGRESS HISTORY"
      onClose={onClose}
      wide
    >
      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
      {history === null && !error ? (
        <div className="list-loading">
          <i />
          <span>正在载入进度历史…</span>
        </div>
      ) : null}
      {history !== null && history.length === 0 ? (
        <EmptyState
          title="暂无进度记录"
          description="开启进度跟踪后，每次调整都会留痕。"
        />
      ) : null}
      {history && history.length > 0 ? (
        <ul className="progress-history">
          {history.map((entry) => (
            <li key={entry.id}>
              <div className="history-head">
                <strong>{historyChangeText(entry)}</strong>
                <span>
                  {formatHistoryTime(entry.changed_at)} ·{" "}
                  {userNames.get(entry.changed_by) ?? "未知用户"}
                </span>
              </div>
              {entry.from_status !== entry.to_status ? (
                <div className="history-line">
                  状态：{statusLabel(entry.from_status)} →{" "}
                  {statusLabel(entry.to_status)}
                </div>
              ) : null}
              {entry.reason ? (
                <div className="history-line">备注：{entry.reason}</div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </Modal>
  );
}

function TaskDeleteModal({
  task,
  descendantCount,
  onClose,
  onDeleted,
}: {
  task: Task;
  descendantCount: number;
  onClose: () => void;
  onDeleted: () => Promise<void>;
}) {
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    const reason = optional(new FormData(event.currentTarget).get("reason"));
    try {
      await api.tasks.remove(task.id, task.revision, reason);
      await onDeleted();
    } catch (caught) {
      setError(apiErrorMessage(caught, "任务删除失败，请稍后重试。"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title="删除任务" eyebrow="DELETE TASK" onClose={onClose}>
      <form className="modal-form" onSubmit={submit}>
        <InlineNotice tone="warning">
          确认删除「{task.title}」？
          {descendantCount > 0
            ? `该任务包含 ${descendantCount} 个子任务，删除会级联删除整棵子树。`
            : "删除后可在审计记录中追溯。"}
        </InlineNotice>
        <label className="field">
          <span>删除原因（可选）</span>
          <textarea
            name="reason"
            rows={3}
            placeholder="补充删除原因，便于审计追溯"
          />
        </label>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" disabled={submitting}>
            {submitting ? "正在删除…" : "确认删除"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function TaskEditModal({
  task,
  users,
  onClose,
  onSaved,
}: {
  task: Task;
  users: UserCandidate[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      await api.tasks.update(task.id, {
        revision: task.revision,
        title: String(form.get("title")).trim(),
        description: optional(form.get("description")),
        priority: String(form.get("priority")),
        due_date: optional(form.get("due_date")),
        collaborator_ids: form
          .getAll("collaborator_ids")
          .map(String)
          .filter((userId) => userId !== task.owner_id),
      });
      await onSaved();
    } catch (caught) {
      setError(apiErrorMessage(caught, "任务编辑失败，请稍后重试。"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title="编辑任务" eyebrow="EDIT TASK" onClose={onClose} wide>
      <form className="modal-form" onSubmit={submit}>
        <div className="form-grid">
          <label className="field field-span-two">
            <span>任务标题 *</span>
            <input
              name="title"
              defaultValue={task.title}
              required
              autoFocus
            />
          </label>
          <label className="field">
            <span>优先级</span>
            <select name="priority" defaultValue={task.priority}>
              <option value="p0">P0 · 紧急</option>
              <option value="p1">P1 · 正常</option>
              <option value="p2">P2 · 较低</option>
            </select>
          </label>
          <label className="field">
            <span>截止日期</span>
            <input
              name="due_date"
              type="date"
              defaultValue={task.due_date ?? ""}
            />
          </label>
          <label className="field field-span-two">
            <span>任务说明</span>
            <textarea
              name="description"
              rows={4}
              defaultValue={task.description ?? ""}
            />
          </label>
          <fieldset className="people-options field-span-two">
            <legend>协作成员</legend>
            {users
              .filter((user) => user.id !== task.owner_id)
              .map((user) => (
                <label key={user.id}>
                  <input
                    type="checkbox"
                    name="collaborator_ids"
                    value={user.id}
                    defaultChecked={task.collaborator_ids.includes(user.id)}
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
            {submitting ? "正在保存…" : "保存任务"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function TaskReassignModal({
  task,
  users,
  onClose,
  onSaved,
}: {
  task: Task;
  users: UserCandidate[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const ownerId = String(form.get("owner_id"));
    const reason = String(form.get("reason") ?? "").trim();
    if (!reason) {
      setError("请填写转派原因。");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await api.tasks.reassign(task.id, {
        revision: task.revision,
        owner_id: ownerId,
        reason,
      });
      await onSaved();
    } catch (caught) {
      setError(apiErrorMessage(caught, "任务转派失败，请稍后重试。"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title="转派任务" eyebrow="REASSIGN TASK" onClose={onClose}>
      <form className="modal-form" onSubmit={submit}>
        <label className="field">
          <span>新负责人 *</span>
          <select name="owner_id" required defaultValue="">
            <option value="" disabled>
              选择新负责人
            </option>
            {users
              .filter((user) => user.id !== task.owner_id)
              .map((user) => (
                <option key={user.id} value={user.id}>
                  {user.display_name}
                </option>
              ))}
          </select>
        </label>
        <label className="field">
          <span>转派原因 *</span>
          <textarea
            name="reason"
            rows={4}
            placeholder="说明职责调整、工作交接或其他转派原因"
            required
          />
        </label>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" disabled={submitting}>
            {submitting ? "正在转派…" : "确认转派"}
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

function taskSourceName(
  task: Task,
  projectNames: Map<string, string>,
  workNames: Map<string, string>,
) {
  if (task.project_id) {
    return projectNames.get(task.project_id) ?? "未知项目";
  }
  if (task.department_work_id) {
    return workNames.get(task.department_work_id) ?? "未知部门工作";
  }
  return "未关联来源";
}

function historyChangeText(entry: TaskProgressHistory) {
  if (!entry.to_enabled) return "关闭进度跟踪";
  if (!entry.from_enabled) {
    return `开启进度跟踪 · ${entry.to_percent ?? 0}%`;
  }
  if (entry.from_percent !== entry.to_percent) {
    return `${entry.from_percent ?? 0}% → ${entry.to_percent ?? 0}%`;
  }
  return "更新进度设置";
}

function statusLabel(status: string) {
  return TASK_STATUS_LABELS[status as TaskStatus] ?? status;
}

function formatHistoryTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function optional(value: FormDataEntryValue | null) {
  const text = String(value ?? "").trim();
  return text || null;
}
