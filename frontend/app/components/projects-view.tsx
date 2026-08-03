"use client";

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, apiErrorMessage, ApiClientError } from "../api";
import type {
  DuplicateCandidate,
  Project,
  ProjectCreationDraft,
  ProjectMergePreview,
  ProjectMergeResult,
  ProjectStatus,
  ProjectSummary,
  ProjectTag,
  User,
  UserCandidate,
} from "../types";
import { canManageProjectObject } from "../object-permissions";
import { AvatarImage } from "./avatar";
import { ChevronRight, Close, Plus, Search } from "./icons";
import { EmptyState, InlineNotice, Modal, StatusBadge } from "./ui";

const transitionOptions: Record<ProjectStatus, ProjectStatus[]> = {
  pending: ["active", "rejected", "archived"],
  active: ["paused", "completed", "archived"],
  paused: ["active", "completed", "archived"],
  completed: ["active", "archived"],
  archived: ["active", "paused", "completed"],
  rejected: ["pending"],
  merged: [],
};

export function ProjectsView({
  canEdit,
  canCreate,
  currentUser,
  creationDraft,
  onCreationDraftHandled,
}: {
  canEdit: boolean;
  canCreate: boolean;
  currentUser: User;
  creationDraft: ProjectCreationDraft | null;
  onCreationDraftHandled: () => void;
}) {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [allProjects, setAllProjects] = useState<ProjectSummary[]>([]);
  const [tags, setTags] = useState<ProjectTag[]>([]);
  const [users, setUsers] = useState<UserCandidate[]>([]);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [selected, setSelected] = useState<Project | null>(null);
  const [mergeOpen, setMergeOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (search.trim()) params.set("q", search.trim());
      if (status) params.set("status", status);
      const projectRowsRequest = api.projects.list(params);
      const allProjectRowsRequest = params.size
        ? api.projects.list()
        : projectRowsRequest;
      const [projectRows, allProjectRows, tagRows, userRows] = await Promise.all([
        projectRowsRequest,
        allProjectRowsRequest,
        api.tags.list(),
        api.users.candidates(),
      ]);
      setProjects(projectRows);
      setAllProjects(allProjectRows);
      setTags(tagRows);
      setUsers(userRows);
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "项目数据加载失败",
      );
    } finally {
      setLoading(false);
    }
  }, [search, status]);

  useEffect(() => {
    const timeout = window.setTimeout(load, 180);
    return () => window.clearTimeout(timeout);
  }, [load]);

  async function openProject(id: string) {
    try {
      setSelected(await api.projects.get(id));
    } catch (caught) {
      setError(caught instanceof ApiClientError ? caught.message : "项目读取失败");
    }
  }

  async function refreshSelected() {
    if (!selected) return;
    const fresh = await api.projects.get(selected.id);
    setSelected(fresh);
    await load();
  }

  return (
    <>
      <div className="view-shell">
        <header className="view-header">
          <div>
            <p className="eyebrow">PROJECT DIRECTORY</p>
            <h1>项目</h1>
            <p>团队唯一的项目主数据，所有任务与工作记录都从这里建立关联。</p>
          </div>
          {canCreate ? (
            <button className="primary-button" onClick={() => setCreateOpen(true)}>
              <Plus size={14} /> 新建项目
            </button>
          ) : null}
        </header>

        <section className="toolbar">
          <label className="search-box">
            <span aria-hidden="true"><Search size={16} /></span>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索项目名称、编号或别名"
            />
          </label>
          <label className="select-filter">
            <span>状态</span>
            <select value={status} onChange={(event) => setStatus(event.target.value)}>
              <option value="">全部状态</option>
              <option value="pending">待确认</option>
              <option value="active">进行中</option>
              <option value="paused">已暂停</option>
              <option value="completed">已完成</option>
              <option value="archived">已归档</option>
              <option value="rejected">已驳回</option>
            </select>
          </label>
          <div className="toolbar-meta">
            <strong>{projects.length}</strong>
            <span>个项目</span>
          </div>
        </section>

        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}

        <section className="data-surface">
          <div className="project-table table-head">
            <span>项目</span>
            <span>标签</span>
            <span>状态</span>
            <span>负责人</span>
            <span>计划周期</span>
            <span />
          </div>
          {loading ? (
            <div className="list-loading">
              <i />
              <span>正在载入项目…</span>
            </div>
          ) : projects.length ? (
            <div className="table-body">
              {projects.map((project) => (
                <button
                  className="project-table project-row"
                  key={project.id}
                  onClick={() => openProject(project.id)}
                >
                  <span className="project-identity">
                    <small>{project.code}</small>
                    <strong>{project.name}</strong>
                    {project.parent_project_id ? <em>子项目</em> : null}
                  </span>
                  <span className="tag-cell">
                    {project.tags.length ? (
                      project.tags.map((tag) => (
                        <i key={tag.id} className={`tag tag-${tag.name}`}>
                          {tag.name}
                        </i>
                      ))
                    ) : (
                      <small className="muted">未标记</small>
                    )}
                  </span>
                  <span>
                    <StatusBadge status={project.status} />
                  </span>
                  <span className="owner-cell">
                    <AvatarImage
                      avatarKey={project.owner_avatar_key}
                      displayName={project.owner_display_name || "未知用户"}
                      decorative
                    />
                    {project.owner_display_name || "未知用户"}
                  </span>
                  <span className="date-cell">
                    {project.planned_start_date || project.planned_end_date
                      ? `${shortDate(project.planned_start_date)} — ${shortDate(
                          project.planned_end_date,
                        )}`
                      : "尚未规划"}
                  </span>
                  <span className="row-action"><ChevronRight size={16} /></span>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState
              title="还没有符合条件的项目"
              description="调整筛选条件，或创建第一个项目。"
            />
          )}
        </section>
      </div>

      {(createOpen || creationDraft) && canCreate ? (
        <ProjectCreateModal
          projects={allProjects}
          tags={tags}
          users={users}
          currentUser={currentUser}
          creationDraft={creationDraft}
          onClose={() => {
            setCreateOpen(false);
            onCreationDraftHandled();
          }}
          onCreated={async (project) => {
            setCreateOpen(false);
            onCreationDraftHandled();
            await load();
            setSelected(project);
          }}
        />
      ) : null}

      {selected ? (
        <ProjectDetailDrawer
          project={selected}
          projects={projects}
          tags={tags}
          users={users}
          canManage={canManageProjectObject(canEdit, currentUser, selected)}
          canMerge={
            canManageProjectObject(canEdit, currentUser, selected) &&
            ["team_leader", "system_admin", "super_admin"].includes(
              currentUser.role,
            ) &&
            selected.status !== "merged"
          }
          onClose={() => setSelected(null)}
          onChanged={refreshSelected}
          onMerge={() => setMergeOpen(true)}
        />
      ) : null}

      {selected && mergeOpen ? (
        <ProjectMergeModal
          source={selected}
          projects={allProjects}
          onClose={() => setMergeOpen(false)}
          onMerged={async (result) => {
            setMergeOpen(false);
            setSelected({
              ...selected,
              status: "merged",
              merged_into_project_id: result.target_project_id,
              revision: selected.revision + 1,
            });
            await load();
            try {
              setSelected(await api.projects.get(selected.id));
            } catch (caught) {
              setError(
                apiErrorMessage(
                  caught,
                  "项目已合并，但最新详情刷新失败，请重新打开项目。",
                ),
              );
            }
          }}
        />
      ) : null}
    </>
  );
}

function ProjectCreateModal({
  projects,
  tags,
  users,
  currentUser,
  creationDraft,
  onClose,
  onCreated,
}: {
  projects: ProjectSummary[];
  tags: ProjectTag[];
  users: UserCandidate[];
  currentUser: User;
  creationDraft: ProjectCreationDraft | null;
  onClose: () => void;
  onCreated: (project: Project) => void;
}) {
  const [name, setName] = useState(creationDraft?.name ?? "");
  const [ownerId, setOwnerId] = useState(creationDraft?.owner_id ?? "");
  const [duplicates, setDuplicates] = useState<DuplicateCandidate[]>([]);
  const [allowSimilar, setAllowSimilar] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function checkDuplicates() {
    if (name.trim().length < 2) return;
    try {
      setDuplicates(await api.projects.duplicates(name.trim()));
    } catch {
      setDuplicates([]);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const tagIds = form.getAll("tag_ids").map(String);
    try {
      const projectPayload = {
        name: name.trim(),
        description: optional(form.get("description")),
        parent_project_id: optional(form.get("parent_project_id")),
        owner_id: ownerId || null,
        planned_start_date: optional(form.get("planned_start_date")),
        planned_end_date: optional(form.get("planned_end_date")),
        tag_ids: tagIds,
        allow_similar_name: allowSimilar,
      };
      const project = creationDraft
        ? (
            await api.opportunities.convertToProject(
              creationDraft.opportunity_id,
              creationDraft.opportunity_revision,
              projectPayload,
            )
          ).project
        : await api.projects.create(projectPayload);
      onCreated(project);
    } catch (caught) {
      if (caught instanceof ApiClientError) {
        setError(caught.message);
        const candidates = caught.details?.candidates;
        if (Array.isArray(candidates)) {
          setDuplicates(candidates as DuplicateCandidate[]);
        }
      } else {
        setError("项目创建失败");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title={creationDraft ? "从商机创建关联项目" : "建立项目主数据"}
      eyebrow={creationDraft ? "CREATE & LINK PROJECT" : "NEW PROJECT"}
      onClose={onClose}
      wide
    >
      <form className="modal-form" onSubmit={submit}>
        {creationDraft ? (
          <InlineNotice tone="info">
            商机 {creationDraft.opportunity_code} 已带入；创建成功后将自动建立唯一关联。
          </InlineNotice>
        ) : null}
        <div className="form-grid">
          <label className="field field-span-two">
            <span>项目标准名称 *</span>
            <input
              name="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              onBlur={checkDuplicates}
              placeholder="使用团队能够长期识别的正式名称"
              required
              autoFocus
            />
          </label>
          {duplicates.length ? (
            <div className="duplicate-panel field-span-two">
              <strong>发现可能重复的项目</strong>
              {duplicates.slice(0, 3).map((candidate) => (
                <div key={`${candidate.project_id}-${candidate.match_type}`}>
                  <span>{candidate.name}</span>
                  <small>
                    {candidate.code} · 相似度{" "}
                    {Math.round(candidate.similarity * 100)}%
                  </small>
                </div>
              ))}
              <label>
                <input
                  type="checkbox"
                  checked={allowSimilar}
                  onChange={(event) => setAllowSimilar(event.target.checked)}
                />
                已确认不是同一项目，仍然创建
              </label>
            </div>
          ) : null}
          <label className="field field-span-two">
            <span>项目说明</span>
            <textarea
              name="description"
              rows={4}
              defaultValue={creationDraft?.description ?? ""}
              placeholder="说明项目目标、范围和关键背景"
            />
          </label>
          <label className="field">
            <span>上级项目</span>
            <select name="parent_project_id">
              <option value="">无，作为一级项目</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>项目负责人</span>
            <select
              name="owner_id"
              value={ownerId}
              onChange={(event) => setOwnerId(event.target.value)}
              required={currentUser.role === "super_admin"}
            >
              {currentUser.role === "super_admin" ? (
                <option value="" disabled>
                  请选择项目负责人
                </option>
              ) : (
                <option value="">由我负责</option>
              )}
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.display_name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>计划开始</span>
            <input name="planned_start_date" type="date" />
          </label>
          <label className="field">
            <span>计划结束</span>
            <input name="planned_end_date" type="date" />
          </label>
          <fieldset className="tag-options field-span-two">
            <legend>项目标签</legend>
            {tags.map((tag) => (
              <label key={tag.id}>
                <input type="checkbox" name="tag_ids" value={tag.id} />
                <span>{tag.name}</span>
                <small>{tag.description}</small>
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
            {submitting
              ? "正在创建…"
              : creationDraft
                ? "创建并关联项目"
                : "创建项目"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function ProjectDetailDrawer({
  project,
  projects,
  tags,
  users,
  canManage,
  canMerge,
  onClose,
  onChanged,
  onMerge,
}: {
  project: Project;
  projects: ProjectSummary[];
  tags: ProjectTag[];
  users: UserCandidate[];
  canManage: boolean;
  canMerge: boolean;
  onClose: () => void;
  onChanged: () => Promise<void>;
  onMerge: () => void;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const currentMembers = project.members.filter((member) => !member.left_at);
  const unusedUsers = users.filter(
    (user) => !currentMembers.some((member) => member.user_id === user.id),
  );
  const unusedTags = tags.filter(
    (tag) => !project.tags.some((assigned) => assigned.id === tag.id),
  );

  async function mutate(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await action();
      await onChanged();
    } catch (caught) {
      setError(caught instanceof ApiClientError ? caught.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside
        className="detail-drawer"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="detail-header">
          <div>
            <p className="eyebrow">{project.code}</p>
            <h2>{project.name}</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="关闭">
            <Close size={14} />
          </button>
        </header>
        <div className="detail-status-line">
          <StatusBadge status={project.status} />
          {project.tags.map((tag) => (
            <span className={`tag tag-${tag.name}`} key={tag.id}>
              {tag.name}
            </span>
          ))}
        </div>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <div className="detail-scroll">
          <section className="detail-section">
            <h3>项目概览</h3>
            <p className="project-description">
              {project.description || "暂未填写项目说明。"}
            </p>
            <dl className="detail-grid">
              <div>
                <dt>负责人</dt>
                <dd>
                  {users.find((user) => user.id === project.owner_id)
                    ?.display_name ?? "未知"}
                </dd>
              </div>
              <div>
                <dt>上级项目</dt>
                <dd>
                  {projects.find((item) => item.id === project.parent_project_id)
                    ?.name ?? "一级项目"}
                </dd>
              </div>
              <div>
                <dt>计划开始</dt>
                <dd>{project.planned_start_date ?? "未设置"}</dd>
              </div>
              <div>
                <dt>计划结束</dt>
                <dd>{project.planned_end_date ?? "未设置"}</dd>
              </div>
            </dl>
          </section>

          <section className="detail-section">
            <div className="section-heading">
              <h3>状态流转</h3>
              <small>当前版本 #{project.revision}</small>
            </div>
            <div className="action-chip-list">
              {canManage
                ? transitionOptions[project.status].map((target) => (
                <button
                  key={target}
                  disabled={busy}
                  onClick={() => {
                    const requiresReason = [
                      "paused",
                      "completed",
                      "archived",
                      "rejected",
                    ].includes(target);
                    const reason = requiresReason
                      ? window.prompt("请填写本次状态变更原因")
                      : "";
                    if (requiresReason && !reason) return;
                    mutate(() =>
                      api.projects.transition(
                        project.id,
                        project.revision,
                        target,
                        reason || undefined,
                      ),
                    );
                  }}
                >
                  转为 <StatusBadge status={target} />
                </button>
                  ))
                : null}
              {canManage && !transitionOptions[project.status].length ? (
                <small className="muted">当前状态没有可执行的下一步。</small>
              ) : !canManage ? (
                <small className="muted">当前账号只有项目查看权限。</small>
              ) : null}
            </div>
          </section>

          <section className="detail-section">
            <div className="section-heading">
              <h3>项目成员</h3>
              <small>{currentMembers.length} 人</small>
            </div>
            <div className="people-list">
              {currentMembers.map((member) => (
                <div key={member.user_id}>
                  <AvatarImage
                    avatarKey={member.avatar_key}
                    displayName={member.display_name}
                    decorative
                  />
                  <span>
                    <strong>{member.display_name}</strong>
                    <small>
                      {member.role === "owner" ? "项目负责人" : "项目成员"}
                    </small>
                  </span>
                </div>
              ))}
            </div>
            {canManage && unusedUsers.length ? (
              <label className="inline-adder">
                <select defaultValue="">
                  <option value="" disabled>
                    选择要加入的成员
                  </option>
                  {unusedUsers.map((user) => (
                    <option key={user.id} value={user.id}>
                      {user.display_name}
                    </option>
                  ))}
                </select>
                <button
                  className="secondary-button"
                  disabled={busy}
                  onClick={(event) => {
                    const select = event.currentTarget
                      .previousElementSibling as HTMLSelectElement;
                    if (!select.value) return;
                    mutate(() =>
                      api.projects.addMember(
                        project.id,
                        project.revision,
                        select.value,
                      ),
                    );
                  }}
                >
                  添加
                </button>
              </label>
            ) : null}
          </section>

          <section className="detail-section">
            <h3>标签与别名</h3>
            <div className="meta-lines">
              <div>
                <span>标签</span>
                <strong>
                  {project.tags.map((tag) => tag.name).join("、") || "无"}
                </strong>
              </div>
              <div>
                <span>别名</span>
                <strong>
                  {project.aliases.map((alias) => alias.value).join("、") || "无"}
                </strong>
              </div>
            </div>
            {canManage ? <div className="compact-adders">
              {unusedTags.length ? (
                <label className="inline-adder">
                  <select defaultValue="">
                    <option value="" disabled>
                      追加标签
                    </option>
                    {unusedTags.map((tag) => (
                      <option key={tag.id} value={tag.id}>
                        {tag.name}
                      </option>
                    ))}
                  </select>
                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={(event) => {
                      const select = event.currentTarget
                        .previousElementSibling as HTMLSelectElement;
                      if (!select.value) return;
                      mutate(() =>
                        api.projects.addTag(
                          project.id,
                          project.revision,
                          select.value,
                        ),
                      );
                    }}
                  >
                    添加
                  </button>
                </label>
              ) : null}
              <button
                className="text-button"
                disabled={busy}
                onClick={() => {
                  const value = window.prompt("输入新的项目别名");
                  if (!value?.trim()) return;
                  mutate(() =>
                    api.projects.addAlias(
                      project.id,
                      project.revision,
                      value.trim(),
                    ),
                  );
                }}
              >
                <Plus size={13} /> 添加别名
              </button>
            </div> : null}
          </section>

          {canMerge ? (
            <section className="detail-section">
              <div className="section-heading">
                <h3>合并项目</h3>
                <small>仅团队负责人和管理员可执行</small>
              </div>
              <p className="project-description">
                先预览会被迁移的数据，再使用来源与目标项目的最新版本确认合并。
              </p>
              <button
                className="secondary-button"
                disabled={busy}
                onClick={onMerge}
              >
                预览并合并
              </button>
            </section>
          ) : null}
        </div>
      </aside>
    </div>
  );
}

function ProjectMergeModal({
  source,
  projects,
  onClose,
  onMerged,
}: {
  source: Project;
  projects: ProjectSummary[];
  onClose: () => void;
  onMerged: (result: ProjectMergeResult) => Promise<void>;
}) {
  const [targetProjectId, setTargetProjectId] = useState("");
  const [preview, setPreview] = useState<ProjectMergePreview | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const target = projects.find((project) => project.id === targetProjectId);
  const candidates = projects.filter(
    (project) => project.id !== source.id && project.status !== "merged",
  );

  async function loadPreview() {
    if (!targetProjectId) {
      setError("请先选择目标项目。");
      return;
    }
    setPreviewing(true);
    setError("");
    setPreview(null);
    try {
      setPreview(
        await api.projects.mergePreview(source.id, targetProjectId),
      );
    } catch (caught) {
      setError(apiErrorMessage(caught, "合并预览失败，请稍后重试。"));
    } finally {
      setPreviewing(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!preview || !target) {
      setError("请先获取当前选择的合并预览。");
      return;
    }
    if (!reason.trim()) {
      setError("请填写合并原因。");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const result = await api.projects.merge(source.id, {
        source_revision: source.revision,
        target_project_id: target.id,
        target_revision: target.revision,
        reason: reason.trim(),
      });
      await onMerged(result);
    } catch (caught) {
      setError(apiErrorMessage(caught, "项目合并失败，请稍后重试。"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title="预览并确认项目合并" eyebrow="MERGE PROJECT" onClose={onClose} wide>
      <form className="modal-form" onSubmit={submit}>
        <div className="form-grid">
          <label className="field">
            <span>来源项目</span>
            <input value={`${source.code} · ${source.name}`} disabled />
          </label>
          <label className="field">
            <span>目标项目 *</span>
            <select
              value={targetProjectId}
              onChange={(event) => {
                setTargetProjectId(event.target.value);
                setPreview(null);
                setError("");
              }}
              required
            >
              <option value="" disabled>
                选择保留的目标项目
              </option>
              {candidates.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.code} · {project.name}
                </option>
              ))}
            </select>
          </label>
          <div className="field-span-two">
            <button
              type="button"
              className="secondary-button"
              disabled={previewing || !targetProjectId}
              onClick={loadPreview}
            >
              {previewing ? "正在计算…" : "获取合并预览"}
            </button>
          </div>

          {preview ? (
            <section className="detail-section field-span-two">
              <div className="section-heading">
                <h3>
                  {preview.source_name} → {preview.target_name}
                </h3>
                <small>以下数据将被移动</small>
              </div>
              <dl className="detail-grid">
                <MergeCount label="任务" value={preview.task_count} />
                <MergeCount label="工时记录" value={preview.work_record_count} />
                <MergeCount label="交付物" value={preview.deliverable_count} />
                <MergeCount label="项目进展" value={preview.progress_count} />
                <MergeCount
                  label="失效任务关系"
                  value={preview.invalidated_task_relation_count}
                />
                <MergeCount label="子项目" value={preview.child_project_count} />
                <MergeCount label="新增成员" value={preview.new_member_count} />
                <MergeCount label="新增标签" value={preview.new_tag_count} />
              </dl>
              {preview.aliases_to_move.length ? (
                <p className="project-description">
                  将迁移别名：{preview.aliases_to_move.join("、")}
                </p>
              ) : null}
            </section>
          ) : null}

          <label className="field field-span-two">
            <span>合并原因 *</span>
            <textarea
              rows={3}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="说明为何确认两个项目属于同一项目"
              required
            />
          </label>
        </div>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button
            className="primary-button"
            disabled={submitting || !preview}
          >
            {submitting ? "正在合并…" : "确认合并"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function MergeCount({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function optional(value: FormDataEntryValue | null) {
  const text = String(value ?? "").trim();
  return text || null;
}

function shortDate(value: string | null) {
  if (!value) return "未定";
  return value.slice(5).replace("-", ".");
}
