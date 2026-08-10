"use client";

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiClientError } from "../api";
import type {
  AuthContext,
  Department,
  DepartmentWork,
  DepartmentWorkStatus,
  DepartmentWorkVisibility,
  PermissionKey,
  UserCandidate,
} from "../types";
import { pinyinMatchAny } from "../pinyin";
import { Plus, Search } from "./icons";
import { EmptyState, InlineNotice, Modal, StatusBadge } from "./ui";

const statusFilters: Array<[DepartmentWorkStatus, string]> = [
  ["in_progress", "进行中"],
  ["completed", "已完成"],
  ["archived", "已归档"],
];

const visibilityLabels: Record<DepartmentWorkVisibility, string> = {
  department_only: "仅本部门",
  public: "全员公开",
};

export function DepartmentWorksView({
  permissions,
  context,
}: {
  permissions: PermissionKey[];
  context: AuthContext;
}) {
  const canView = permissions.includes("department_works.view");
  const canCreate = permissions.includes("department_works.create");
  const canEdit = permissions.includes("department_works.edit");

  const [works, setWorks] = useState<DepartmentWork[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [users, setUsers] = useState<UserCandidate[]>([]);
  const [search, setSearch] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [status, setStatus] = useState<DepartmentWorkStatus>("in_progress");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<DepartmentWork | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      params.set("status", status);
      if (status === "archived") params.set("include_archived", "true");
      if (departmentId) params.set("department_id", departmentId);
      const [workRows, departmentRows, userRows] = await Promise.all([
        api.departmentWorks.list(params),
        api.departments.list(),
        api.users.candidates(),
      ]);
      setWorks(workRows);
      setDepartments(departmentRows);
      setUsers(userRows);
    } catch (caught) {
      setError(
        caught instanceof ApiClientError
          ? caught.message
          : "部门工作数据加载失败",
      );
    } finally {
      setLoading(false);
    }
  }, [status, departmentId]);

  useEffect(() => {
    const timeout = window.setTimeout(load, 180);
    return () => window.clearTimeout(timeout);
  }, [load]);

  const filtered = works.filter((work) =>
    pinyinMatchAny(
      [work.name, work.code, work.department_name, work.owner_display_name],
      search,
    ),
  );

  async function runAction(action: () => Promise<unknown>) {
    setError("");
    try {
      await action();
      await load();
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "操作失败，请重试",
      );
    }
  }

  function archiveWork(work: DepartmentWork) {
    if (!window.confirm(`确认归档「${work.name}」吗？归档后将变为只读。`)) return;
    runAction(() =>
      api.departmentWorks.transition(work.id, work.revision, "archived"),
    );
  }

  function removeWork(work: DepartmentWork) {
    if (!window.confirm(`确认删除「${work.name}」吗？此操作不可恢复。`)) return;
    const reason = window.prompt("可填写删除原因（可选）");
    runAction(() =>
      api.departmentWorks.remove(work.id, work.revision, reason || undefined),
    );
  }

  if (!canView) {
    return (
      <div className="view-shell">
        <EmptyState
          title="没有查看权限"
          description="当前账号没有部门工作的查看权限，请联系管理员开通。"
        />
      </div>
    );
  }

  return (
    <>
      <div className="view-shell">
        <header className="view-header">
          <div>
            <p className="eyebrow">DEPARTMENT WORK</p>
            <h1>部门工作</h1>
            <p>沉淀跨部门事项与协作，让部门级工作有统一的入口与节奏。</p>
          </div>
          {canCreate ? (
            <button className="primary-button" onClick={() => setCreateOpen(true)}>
              <Plus size={14} /> 新建部门工作
            </button>
          ) : null}
        </header>

        <section className="toolbar">
          <label className="search-box">
            <span aria-hidden="true">
              <Search size={16} />
            </span>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索名称、编号、部门或负责人"
            />
          </label>
          <label className="select-filter">
            <span>部门</span>
            <select
              value={departmentId}
              onChange={(event) => setDepartmentId(event.target.value)}
            >
              <option value="">全部部门</option>
              {departments.map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name}
                </option>
              ))}
            </select>
          </label>
          <div className="segmented-filter" aria-label="状态筛选">
            {statusFilters.map(([value, label]) => (
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
            <strong>{filtered.length}</strong>
            <span>项部门工作</span>
          </div>
        </section>

        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}

        <section className="data-surface">
          <div className="department-work-table table-head">
            <span>事项</span>
            <span>部门</span>
            <span>负责人</span>
            <span>状态</span>
            <span>可见性</span>
            <span>操作</span>
          </div>
          {loading ? (
            <div className="list-loading">
              <i />
              <span>正在载入部门工作…</span>
            </div>
          ) : filtered.length ? (
            <div className="table-body">
              {filtered.map((work) => (
                <div className="department-work-table department-work-row" key={work.id}>
                  <span className="department-work-identity">
                    <small>{work.code}</small>
                    <strong>{work.name}</strong>
                    {work.description ? <em>{work.description}</em> : null}
                  </span>
                  <span>{work.department_name || "—"}</span>
                  <span>{work.owner_display_name || "未知用户"}</span>
                  <span>
                    <StatusBadge status={work.status} />
                  </span>
                  <span>
                    <i className="tag">{visibilityLabels[work.visibility]}</i>
                  </span>
                  <span className="department-work-actions">
                    {canEdit && work.status !== "archived" ? (
                      <>
                        <button
                          className="text-button"
                          onClick={() => setEditing(work)}
                        >
                          编辑
                        </button>
                        {work.status === "in_progress" ? (
                          <button
                            className="text-button"
                            onClick={() =>
                              runAction(() =>
                                api.departmentWorks.transition(
                                  work.id,
                                  work.revision,
                                  "completed",
                                ),
                              )
                            }
                          >
                            完成
                          </button>
                        ) : null}
                        {work.status === "completed" ? (
                          <button
                            className="text-button"
                            onClick={() =>
                              runAction(() =>
                                api.departmentWorks.transition(
                                  work.id,
                                  work.revision,
                                  "in_progress",
                                ),
                              )
                            }
                          >
                            重新开启
                          </button>
                        ) : null}
                        <button
                          className="text-button"
                          onClick={() => archiveWork(work)}
                        >
                          归档
                        </button>
                        <button
                          className="text-button danger"
                          onClick={() => removeWork(work)}
                        >
                          删除
                        </button>
                      </>
                    ) : (
                      <small className="muted">
                        {work.status === "archived" ? "已归档，只读" : "仅查看"}
                      </small>
                    )}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              title="还没有符合条件的部门工作"
              description="调整筛选条件，或创建第一项部门工作。"
            />
          )}
        </section>
      </div>

      {(createOpen || editing) && (canCreate || editing) ? (
        <DepartmentWorkFormModal
          work={editing}
          departments={departments}
          users={users}
          context={context}
          onClose={() => {
            setCreateOpen(false);
            setEditing(null);
          }}
          onSaved={async () => {
            setCreateOpen(false);
            setEditing(null);
            await load();
          }}
        />
      ) : null}
    </>
  );
}

function DepartmentWorkFormModal({
  work,
  departments,
  users,
  context,
  onClose,
  onSaved,
}: {
  work: DepartmentWork | null;
  departments: Department[];
  users: UserCandidate[];
  context: AuthContext;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const editing = work !== null;
  const primaryDepartmentId = context.user.primary_department_id ?? "";
  const [name, setName] = useState(work?.name ?? "");
  const [departmentId, setDepartmentId] = useState(
    work?.department_id ?? primaryDepartmentId,
  );
  const [ownerId, setOwnerId] = useState(work?.owner_id ?? "");
  const [visibility, setVisibility] = useState<DepartmentWorkVisibility>(
    work?.visibility ?? "department_only",
  );
  const [description, setDescription] = useState(work?.description ?? "");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      if (editing && work) {
        await api.departmentWorks.update(work.id, {
          revision: work.revision,
          name: name.trim(),
          description: description.trim() || null,
          owner_id: ownerId || null,
          visibility,
        });
      } else {
        await api.departmentWorks.create({
          name: name.trim(),
          description: description.trim() || null,
          department_id: departmentId || null,
          owner_id: ownerId || null,
          visibility,
        });
      }
      await onSaved();
    } catch (caught) {
      setError(
        caught instanceof ApiClientError
          ? caught.message
          : editing
            ? "部门工作保存失败"
            : "部门工作创建失败",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title={editing ? "编辑部门工作" : "新建部门工作"}
      eyebrow={editing ? "EDIT DEPARTMENT WORK" : "NEW DEPARTMENT WORK"}
      onClose={onClose}
    >
      <form className="modal-form" onSubmit={submit}>
        <div className="form-grid">
          <label className="field field-span-two">
            <span>事项名称 *</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="使用团队能够长期识别的正式名称"
              required
              autoFocus
            />
          </label>
          <label className="field">
            <span>所属部门</span>
            <select
              value={departmentId}
              onChange={(event) => setDepartmentId(event.target.value)}
              disabled={editing}
              required={!editing && !primaryDepartmentId}
            >
              {editing ? null : (
                <option value="">
                  {primaryDepartmentId
                    ? "跟随我的主部门"
                    : "请选择所属部门"}
                </option>
              )}
              {departments.map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>负责人</span>
            <select
              value={ownerId}
              onChange={(event) => setOwnerId(event.target.value)}
            >
              <option value="">由我负责</option>
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.display_name}
                </option>
              ))}
            </select>
          </label>
          <fieldset className="field field-span-two visibility-options">
            <span>可见性</span>
            <div className="segmented-filter" aria-label="可见性">
              {(
                [
                  ["department_only", "仅本部门可见"],
                  ["public", "全员公开"],
                ] as Array<[DepartmentWorkVisibility, string]>
              ).map(([value, label]) => (
                <button
                  type="button"
                  key={value}
                  className={visibility === value ? "active" : ""}
                  onClick={() => setVisibility(value)}
                >
                  {label}
                </button>
              ))}
            </div>
          </fieldset>
          <label className="field field-span-two">
            <span>事项说明</span>
            <textarea
              rows={4}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="说明事项目标、范围和协作方式"
            />
          </label>
        </div>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" disabled={submitting}>
            {submitting
              ? editing
                ? "正在保存…"
                : "正在创建…"
              : editing
                ? "保存修改"
                : "创建部门工作"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}
