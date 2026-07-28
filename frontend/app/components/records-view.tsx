"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiClientError } from "../api";
import type { ProjectSummary, Task, WorkRecord } from "../types";
import { AvatarImage } from "./avatar";
import { EmptyState, InlineNotice, Modal } from "./ui";

export function RecordsView() {
  const [records, setRecords] = useState<WorkRecord[]>([]);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [projectId, setProjectId] = useState("");
  const [unassignedOnly, setUnassignedOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (projectId) params.set("project_id", projectId);
      if (unassignedOnly) params.set("unassigned_only", "true");
      const [recordRows, projectRows, taskRows] = await Promise.all([
        api.records.list(params),
        api.projects.list(),
        api.tasks.list(),
      ]);
      setRecords(recordRows);
      setProjects(projectRows);
      setTasks(taskRows);
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "工作记录加载失败",
      );
    } finally {
      setLoading(false);
    }
  }, [projectId, unassignedOnly]);

  useEffect(() => {
    const timeout = window.setTimeout(load, 0);
    return () => window.clearTimeout(timeout);
  }, [load]);

  const projectNames = useMemo(
    () => new Map(projects.map((project) => [project.id, project.name])),
    [projects],
  );
  const taskNames = useMemo(
    () => new Map(tasks.map((task) => [task.id, task.title])),
    [tasks],
  );
  const totalMinutes = records.reduce((sum, record) => sum + record.minutes, 0);

  return (
    <div className="view-shell">
      <header className="view-header">
        <div>
          <p className="eyebrow">WORK LOG</p>
          <h1>工作记录</h1>
          <p>按项目沉淀每天的有效工作，为后续周报归纳提供可追溯依据。</p>
        </div>
        <button className="primary-button" onClick={() => setCreateOpen(true)}>
          <span>＋</span> 记录工作
        </button>
      </header>

      <section className="toolbar">
        <label className="select-filter select-wide">
          <span>关联项目</span>
          <select
            value={projectId}
            disabled={unassignedOnly}
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
        <label className="toggle-filter">
          <input
            type="checkbox"
            checked={unassignedOnly}
            onChange={(event) => setUnassignedOnly(event.target.checked)}
          />
          <span />
          仅看待归集
        </label>
        <div className="toolbar-meta">
          <strong>{formatHours(totalMinutes)}</strong>
          <span>累计工时</span>
        </div>
      </section>

      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
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
                          className={record.project_id ? "linked" : "unassigned"}
                        >
                          {record.project_id
                            ? projectNames.get(record.project_id) ?? "未知项目"
                            : "待归集"}
                        </span>
                        <span className="record-author">
                          <AvatarImage
                            avatarKey={record.author_avatar_key}
                            displayName={record.author_display_name}
                            decorative
                          />
                          记录人：{record.author_display_name}
                        </span>
                      </div>
                      <strong>{formatHours(record.minutes)}</strong>
                    </div>
                    <p>{record.content}</p>
                    {record.task_id ? (
                      <div className="record-task">
                        任务 · {taskNames.get(record.task_id) ?? "未知任务"}
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
                            <span>↗</span>
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
            description="记录今天完成的工作，并尽量关联到正确项目。"
          />
        )}
      </section>

      {createOpen ? (
        <RecordCreateModal
          projects={projects}
          tasks={tasks}
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

function RecordCreateModal({
  projects,
  tasks,
  onClose,
  onCreated,
}: {
  projects: ProjectSummary[];
  tasks: Task[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [selectedProject, setSelectedProject] = useState("");
  const [deliverableEnabled, setDeliverableEnabled] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const visibleTasks = selectedProject
    ? tasks.filter((task) => task.project_id === selectedProject)
    : tasks;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const taskId = optional(form.get("task_id"));
    const task = tasks.find((item) => item.id === taskId);
    const projectId = task?.project_id ?? optional(form.get("project_id"));
    const hours = Number(form.get("hours"));
    const deliverableName = optional(form.get("deliverable_name"));
    const deliverableUrl = optional(form.get("deliverable_url"));
    try {
      await api.records.create({
        work_date: String(form.get("work_date")),
        content: String(form.get("content")),
        minutes: hours * 60,
        project_id: projectId,
        task_id: taskId,
        risk: optional(form.get("risk")),
        next_action: optional(form.get("next_action")),
        deliverables:
          deliverableEnabled && deliverableName && deliverableUrl
            ? [{ name: deliverableName, url: deliverableUrl }]
            : [],
      });
      onCreated();
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "工作记录保存失败",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title="记录今天的有效工作" eyebrow="NEW WORK LOG" onClose={onClose} wide>
      <form className="modal-form" onSubmit={submit}>
        <div className="form-grid">
          <label className="field">
            <span>工作日期 *</span>
            <input
              name="work_date"
              type="date"
              defaultValue={new Date().toISOString().slice(0, 10)}
              required
            />
          </label>
          <label className="field">
            <span>投入时长（小时）*</span>
            <input
              name="hours"
              type="number"
              min="0.5"
              max="24"
              step="0.5"
              defaultValue="1"
              required
            />
          </label>
          <label className="field">
            <span>关联项目</span>
            <select
              name="project_id"
              value={selectedProject}
              onChange={(event) => setSelectedProject(event.target.value)}
            >
              <option value="">暂不归集</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>关联任务</span>
            <select name="task_id" defaultValue="">
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
                onChange={(event) => setDeliverableEnabled(event.target.checked)}
              />
              <span />
              添加产出物链接
            </label>
          </div>
          {deliverableEnabled ? (
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
            {submitting ? "正在保存…" : "保存记录"}
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

function optional(value: FormDataEntryValue | null) {
  const text = String(value ?? "").trim();
  return text || null;
}
