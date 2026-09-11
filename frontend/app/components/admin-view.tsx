"use client";

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiClientError } from "../api";
import { pinyinMatchAny } from "../pinyin";
import type {
  AuditEvent,
  AuthContext,
  Department,
  PermissionDefinition,
  PermissionKey,
  ProjectTag,
  User,
  UserCandidate,
  UserPermissions,
  UserRole,
} from "../types";
import { AIConfigPanel } from "./ai-config-panel";
import { AvatarImage } from "./avatar";
import { Dice, Plus, Search } from "./icons";
import { EmptyState, InlineNotice, Modal } from "./ui";

type AdminTab = "users" | "departments" | "tags" | "ai" | "audit";

export function AdminView({ context }: { context: AuthContext }) {
  const permissions = context.permissions ?? [];
  const canManagePermissions = ["system_admin", "super_admin"].includes(
    context.user.role,
  );
  const canManageUsers = permissions.includes("settings.users.manage");
  const canManageTags = permissions.includes("settings.tags.manage");
  const canManageAi = permissions.includes("settings.ai.manage");
  const canViewAudit = permissions.includes("settings.audit.view");
  const canViewDepartments = permissions.includes("departments.view");
  const canManageDepartments = permissions.includes("departments.manage");
  const showUsers = canManagePermissions || canManageUsers;
  const [users, setUsers] = useState<User[]>([]);
  const [tags, setTags] = useState<ProjectTag[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [departmentCandidates, setDepartmentCandidates] = useState<
    UserCandidate[]
  >([]);
  const [departmentsLoading, setDepartmentsLoading] = useState(false);
  const [departmentSearch, setDepartmentSearch] = useState("");
  const [showInactiveDepartments, setShowInactiveDepartments] = useState(false);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [tab, setTab] = useState<AdminTab>(
    showUsers
      ? "users"
      : canViewDepartments
        ? "departments"
        : canManageTags
          ? "tags"
          : canManageAi
            ? "ai"
            : "audit",
  );
  const [createUserOpen, setCreateUserOpen] = useState(false);
  const [createTagOpen, setCreateTagOpen] = useState(false);
  const [createDepartmentOpen, setCreateDepartmentOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [editingTag, setEditingTag] = useState<ProjectTag | null>(null);
  const [editingDepartment, setEditingDepartment] = useState<Department | null>(
    null,
  );
  const [permissionUser, setPermissionUser] = useState<User | null>(null);
  const [departmentMembersView, setDepartmentMembersView] =
    useState<Department | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [userRows, tagRows, auditRows] = await Promise.all([
        showUsers || canViewDepartments
          ? api.users.list(true)
          : Promise.resolve([]),
        canManageTags ? api.tags.list(true) : Promise.resolve([]),
        canViewAudit ? api.audit.list() : Promise.resolve([]),
      ]);
      setUsers(userRows);
      setTags(tagRows);
      setAuditEvents(auditRows);
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "基础数据加载失败",
      );
    }
  }, [canManageTags, canViewAudit, showUsers, canViewDepartments]);

  const loadDepartments = useCallback(async () => {
    if (!canViewDepartments) return;
    setDepartmentsLoading(true);
    try {
      const [departmentRows, candidateRows] = await Promise.all([
        api.departments.list(showInactiveDepartments),
        api.users.candidates(),
      ]);
      setDepartments(departmentRows);
      setDepartmentCandidates(candidateRows);
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "部门数据加载失败",
      );
    } finally {
      setDepartmentsLoading(false);
    }
  }, [canViewDepartments, showInactiveDepartments]);

  useEffect(() => {
    const timeout = window.setTimeout(load, 0);
    return () => window.clearTimeout(timeout);
  }, [load]);

  useEffect(() => {
    const timeout = window.setTimeout(loadDepartments, 0);
    return () => window.clearTimeout(timeout);
  }, [loadDepartments]);

  const userNameById = new Map<string, string>();
  for (const candidate of departmentCandidates) {
    userNameById.set(candidate.id, candidate.display_name);
  }
  for (const user of users) {
    userNameById.set(user.id, user.display_name);
  }
  const visibleDepartments = departments.filter((department) =>
    pinyinMatchAny([department.name], departmentSearch),
  );

  async function removeDepartment(department: Department) {
    if (
      !window.confirm(
        `确认删除部门“${department.name}”？删除为软删除，可在审计记录中追溯。`,
      )
    ) {
      return;
    }
    const reason = window.prompt("请输入删除原因（可选）：");
    if (reason === null) return;
    setError("");
    try {
      await api.departments.remove(
        department.id,
        department.revision,
        reason.trim() || null,
      );
      await loadDepartments();
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "部门删除失败",
      );
    }
  }

  return (
    <div className="view-shell">
      <header className="view-header">
        <div>
          <p className="eyebrow">SYSTEM SETTINGS</p>
          <h1>系统设置</h1>
          <p>维护本地用户、权限、项目标签、大模型接入与审计记录。</p>
        </div>
        {(tab === "users" && canManageUsers) ||
        (tab === "departments" && canManageDepartments) ||
        (tab === "tags" && canManageTags) ? (
          <button
            className="primary-button"
            onClick={() =>
              tab === "users"
                ? setCreateUserOpen(true)
                : tab === "departments"
                  ? setCreateDepartmentOpen(true)
                  : setCreateTagOpen(true)
            }
          >
            <Plus size={14} />{" "}
            {tab === "users"
              ? "创建用户"
              : tab === "departments"
                ? "创建部门"
                : "创建标签"}
          </button>
        ) : null}
      </header>

      <div className="section-tabs">
        {showUsers ? (
          <button
            className={tab === "users" ? "active" : ""}
            onClick={() => setTab("users")}
          >
            用户与权限 <span>{users.length}</span>
          </button>
        ) : null}
        {canViewDepartments ? (
          <button
            className={tab === "departments" ? "active" : ""}
            onClick={() => setTab("departments")}
          >
            部门 <span>{departments.length}</span>
          </button>
        ) : null}
        {canManageTags ? (
          <button
            className={tab === "tags" ? "active" : ""}
            onClick={() => setTab("tags")}
          >
            项目标签 <span>{tags.length}</span>
          </button>
        ) : null}
        {canManageAi ? (
          <button
            className={tab === "ai" ? "active" : ""}
            onClick={() => setTab("ai")}
          >
            大模型接入 <span>AI</span>
          </button>
        ) : null}
        {canViewAudit ? (
          <button
            className={tab === "audit" ? "active" : ""}
            onClick={() => setTab("audit")}
          >
            审计记录 <span>{auditEvents.length}</span>
          </button>
        ) : null}
      </div>
      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}

      {tab === "users" ? (
        <section className="admin-grid">
          {users.length ? (
            users.map((user) => (
              <article className="user-card" key={user.id}>
                <AvatarImage
                  avatarKey={user.avatar_key}
                  displayName={user.display_name}
                  className="avatar-large"
                  decorative
                />
                <div>
                  <h3>{user.display_name}</h3>
                  <p>@{user.login_name}</p>
                </div>
                <span className={`role-pill role-${user.role}`}>
                  {roleLabel(user.role)}
                </span>
                <small>{user.is_active ? "账号正常" : "已冻结"}</small>
                <div className="user-card-management">
                  <span>
                    直属 Leader
                    <strong>
                      {users.find((candidate) => candidate.id === user.leader_id)
                        ?.display_name ?? "未指定"}
                    </strong>
                  </span>
                  {user.primary_department_id &&
                  departments.some(
                    (department) => department.id === user.primary_department_id,
                  ) ? (
                    <span>
                      主部门
                      <strong>
                        {
                          departments.find(
                            (department) =>
                              department.id === user.primary_department_id,
                          )?.name
                        }
                      </strong>
                    </span>
                  ) : null}
                  <div className="user-card-actions">
                    {canManagePermissions &&
                    (context.user.role === "super_admin" ||
                      ["member", "team_leader"].includes(user.role)) ? (
                      <button
                        type="button"
                        className="primary-button compact"
                        onClick={() => setPermissionUser(user)}
                      >
                        配置权限
                      </button>
                    ) : null}
                    {canManageUsers &&
                    (context.user.role === "super_admin" ||
                      user.role !== "system_admin") ? (
                      <button
                        type="button"
                        className="secondary-button compact"
                        onClick={() => setEditingUser(user)}
                      >
                        编辑资料
                      </button>
                    ) : null}
                  </div>
                </div>
              </article>
            ))
          ) : (
            <EmptyState title="暂无用户" description="创建团队的第一个业务账号。" />
          )}
        </section>
      ) : tab === "departments" ? (
        <>
          <section className="toolbar">
            <label className="search-box">
              <span aria-hidden="true">
                <Search size={16} />
              </span>
              <input
                value={departmentSearch}
                onChange={(event) => setDepartmentSearch(event.target.value)}
                placeholder="搜索部门名称"
              />
            </label>
            <label className="toggle-filter">
              <input
                type="checkbox"
                checked={showInactiveDepartments}
                onChange={(event) =>
                  setShowInactiveDepartments(event.target.checked)
                }
              />
              <span />
              显示已停用
            </label>
            <div className="toolbar-meta">
              <strong>{visibleDepartments.length}</strong>
              <span>个部门</span>
            </div>
          </section>
          {departmentsLoading ? (
            <div className="list-loading">
              <i />
              <span>正在载入部门…</span>
            </div>
          ) : visibleDepartments.length ? (
            <section className="tag-admin-list department-admin-list">
              {visibleDepartments.map((department, index) => (
                <article key={department.id}>
                  <span className={`tag-number tag-number-${index % 4}`}>
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <h3>{department.name}</h3>
                    <p>
                      负责人：
                      {(department.leader_id &&
                        userNameById.get(department.leader_id)) ||
                        "未指定"}
                    </p>
                  </div>
                  <span className="tag">
                    {department.is_active ? "启用" : "已停用"}
                  </span>
                  <div className="user-card-actions">
                    <button
                      type="button"
                      className="text-button"
                      onClick={() => setDepartmentMembersView(department)}
                    >
                      查看成员
                    </button>
                    {canManageDepartments ? (
                      <>
                        <button
                          type="button"
                          className="text-button"
                          onClick={() => setEditingDepartment(department)}
                        >
                          编辑
                        </button>
                        <button
                          type="button"
                          className="text-button"
                          onClick={() => removeDepartment(department)}
                        >
                          删除
                        </button>
                      </>
                    ) : null}
                  </div>
                </article>
              ))}
            </section>
          ) : (
            <EmptyState
              title="暂无部门"
              description={
                departmentSearch
                  ? "没有匹配搜索条件的部门。"
                  : "创建团队的第一个部门。"
              }
            />
          )}
        </>
      ) : tab === "tags" ? (
        <section className="tag-admin-list">
          {tags.map((tag, index) => (
            <article key={tag.id}>
              <span className={`tag-number tag-number-${index % 4}`}>
                {String(index + 1).padStart(2, "0")}
              </span>
              <div>
                <h3>{tag.name}</h3>
                <p>{tag.description || "暂未填写标签说明。"}</p>
              </div>
              <span className={`tag tag-${tag.name}`}>{tag.name}</span>
              <div className="user-card-actions">
                <small>{tag.is_active ? "使用中" : "已停用"}</small>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setEditingTag(tag)}
                >
                  编辑
                </button>
              </div>
            </article>
          ))}
        </section>
      ) : tab === "ai" && canManageAi ? (
        <AIConfigPanel />
      ) : tab === "audit" && canViewAudit ? (
        auditEvents.length ? (
          <section className="audit-admin-list">
            {auditEvents.map((event) => (
              <article key={event.id}>
                <div>
                  <strong>{event.action}</strong>
                  <span>
                    {event.entity_type}
                    {event.entity_id ? ` · ${event.entity_id}` : ""}
                  </span>
                </div>
                <span className={`audit-result audit-result-${event.result}`}>
                  {event.result}
                </span>
                <time dateTime={event.created_at}>
                  {new Intl.DateTimeFormat("zh-CN", {
                    dateStyle: "short",
                    timeStyle: "medium",
                  }).format(new Date(event.created_at))}
                </time>
              </article>
            ))}
          </section>
        ) : (
          <EmptyState
            title="暂无审计记录"
            description="新的受审计操作会显示在这里。"
          />
        )
      ) : null}

      {createUserOpen && canManageUsers ? (
        <UserCreateModal
          canCreateSystemAdmin={context.user.role === "super_admin"}
          departments={canViewDepartments ? departments : null}
          onClose={() => setCreateUserOpen(false)}
          onCreated={async () => {
            await load();
          }}
        />
      ) : null}
      {createDepartmentOpen && canManageDepartments ? (
        <DepartmentCreateModal
          candidates={departmentCandidates}
          onClose={() => setCreateDepartmentOpen(false)}
          onCreated={async () => {
            setCreateDepartmentOpen(false);
            await loadDepartments();
          }}
        />
      ) : null}
      {departmentMembersView ? (
        <DepartmentMembersModal
          department={departmentMembersView}
          users={users}
          onClose={() => setDepartmentMembersView(null)}
        />
      ) : null}
      {createTagOpen && canManageTags ? (
        <TagCreateModal
          onClose={() => setCreateTagOpen(false)}
          onCreated={async () => {
            setCreateTagOpen(false);
            await load();
          }}
        />
      ) : null}
      {editingTag && canManageTags ? (
        <TagEditModal
          tag={editingTag}
          onClose={() => setEditingTag(null)}
          onUpdated={async () => {
            setEditingTag(null);
            await load();
          }}
        />
      ) : null}
      {editingDepartment && canManageDepartments ? (
        <DepartmentEditModal
          department={editingDepartment}
          candidates={departmentCandidates}
          onClose={() => setEditingDepartment(null)}
          onUpdated={async () => {
            setEditingDepartment(null);
            await loadDepartments();
          }}
        />
      ) : null}
      {editingUser && canManageUsers ? (
        <UserEditModal
          user={editingUser}
          users={users}
          departments={canViewDepartments ? departments : null}
          canManageSystemAdmins={context.user.role === "super_admin"}
          currentUserId={context.user.id}
          actorRole={context.user.role}
          onClose={() => setEditingUser(null)}
          onUpdated={async () => {
            setEditingUser(null);
            await load();
          }}
        />
      ) : null}
      {permissionUser && canManagePermissions ? (
        <PermissionModal
          user={permissionUser}
          actorRole={context.user.role}
          hasDirectReports={users.some(
            (candidate) =>
              candidate.is_active && candidate.leader_id === permissionUser.id,
          )}
          onClose={() => setPermissionUser(null)}
          onSaved={async () => {
            setPermissionUser(null);
            await load();
          }}
        />
      ) : null}
    </div>
  );
}

function UserCreateModal({
  canCreateSystemAdmin,
  departments,
  onClose,
  onCreated,
}: {
  canCreateSystemAdmin: boolean;
  departments: Department[] | null;
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [initialPassword, setInitialPassword] = useState("");
  const [showInitialPassword, setShowInitialPassword] = useState(false);
  const [createdUser, setCreatedUser] = useState<User | null>(null);
  const [copied, setCopied] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSubmitting(true);
    setError("");
    try {
      const created = await api.users.create({
        display_name: String(form.get("display_name")),
        password: String(form.get("password")),
        role: String(form.get("role")),
        ...(departments
          ? {
              primary_department_id:
                String(form.get("primary_department_id") || "") || null,
            }
          : {}),
      });
      setCreatedUser(created);
      await onCreated();
    } catch (caught) {
      setError(caught instanceof ApiClientError ? caught.message : "用户创建失败");
    } finally {
      setSubmitting(false);
    }
  }

  async function copyCredential(value: string, label: string) {
    await navigator.clipboard.writeText(value);
    setCopied(`${label}已复制`);
  }

  if (createdUser) {
    return (
      <Modal title="账号创建成功" eyebrow="ACCOUNT READY" onClose={onClose}>
        <div className="modal-form credential-result">
          <InlineNotice>
            用户可使用显示名称或登录名登录。请将下列信息一次性交付给用户；首次登录后，
            用户必须修改初始密码。
          </InlineNotice>
          <dl>
            <div>
              <dt>姓名</dt>
              <dd>{createdUser.display_name}</dd>
            </div>
            <div>
              <dt>登录名</dt>
              <dd>
                <code>{createdUser.login_name}</code>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => copyCredential(createdUser.login_name, "登录名")}
                >
                  复制
                </button>
              </dd>
            </div>
            <div>
              <dt>初始密码</dt>
              <dd>
                <code>{initialPassword}</code>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => copyCredential(initialPassword, "初始密码")}
                >
                  复制
                </button>
              </dd>
            </div>
          </dl>
          {copied ? <p className="copy-feedback">{copied}</p> : null}
          <footer className="modal-actions">
            <button className="primary-button" type="button" onClick={onClose}>
              完成
            </button>
          </footer>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title="创建本地用户" eyebrow="NEW USER" onClose={onClose}>
      <form className="modal-form" onSubmit={submit}>
        <label className="field">
          <span>显示名称 *</span>
          <input name="display_name" required autoFocus placeholder="例如 张三" />
          <small className="field-hint">
            显示名称全系统唯一，也可以直接用于登录。
          </small>
        </label>
        <label className="field">
          <span>初始密码 *</span>
          <div className="password-input-row">
            <input
              name="password"
              type={showInitialPassword ? "text" : "password"}
              minLength={10}
              value={initialPassword}
              onChange={(event) => setInitialPassword(event.target.value)}
              autoComplete="new-password"
              required
            />
            <button
              type="button"
              className="password-dice"
              aria-label="生成高强度随机密码"
              title="生成高强度随机密码"
              onClick={() => {
                setInitialPassword(generateStrongInitialPassword());
                setShowInitialPassword(true);
              }}
            >
              <Dice size={18} />
            </button>
          </div>
          <small className="field-hint">
            至少10位；点击骰子生成20位数字、字母和符号组合。
          </small>
        </label>
        <label className="field">
          <span>角色</span>
          <select name="role" defaultValue="member">
            <option value="member">团队成员</option>
            <option value="team_leader">团队负责人</option>
            {canCreateSystemAdmin ? (
              <option value="system_admin">系统管理员</option>
            ) : null}
          </select>
        </label>
        {departments ? (
          <label className="field">
            <span>主部门</span>
            <select name="primary_department_id" defaultValue="">
              <option value="">未分配</option>
              {departments
                .filter((department) => department.is_active)
                .map((department) => (
                  <option key={department.id} value={department.id}>
                    {department.name}
                  </option>
                ))}
            </select>
            <small className="field-hint">
              主部门决定用户在部门工作和作战台中的归属，可稍后再分配。
            </small>
          </label>
        ) : null}
        <InlineNotice>
          登录名由系统自动生成。直属 Leader 可在账号创建后通过“编辑资料”配置；超级管理员账号仍只能通过服务器命令创建。
        </InlineNotice>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" disabled={submitting}>
            {submitting ? "正在创建…" : "创建用户"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function UserEditModal({
  user,
  users,
  departments,
  canManageSystemAdmins,
  currentUserId,
  actorRole,
  onClose,
  onUpdated,
}: {
  user: User;
  users: User[];
  departments: Department[] | null;
  canManageSystemAdmins: boolean;
  currentUserId: string;
  actorRole: UserRole;
  onClose: () => void;
  onUpdated: () => void;
}) {
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [freezeBusy, setFreezeBusy] = useState(false);
  const canFreeze =
    user.id !== currentUserId &&
    (user.role !== "system_admin" || actorRole === "super_admin");
  const leaderCandidates = users.filter(
    (candidate) =>
      candidate.id !== user.id &&
      ["team_leader", "system_admin"].includes(candidate.role) &&
      candidate.is_active,
  );
  const activeDepartments = (departments ?? []).filter(
    (department) => department.is_active,
  );
  const currentDepartmentMissing =
    departments !== null &&
    user.primary_department_id !== null &&
    !activeDepartments.some(
      (department) => department.id === user.primary_department_id,
    );

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSubmitting(true);
    setError("");
    try {
      await api.users.update(user.id, {
        revision: user.revision,
        display_name: String(form.get("display_name")),
        role: String(form.get("role")),
        leader_id: String(form.get("leader_id") || "") || null,
        ...(departments
          ? {
              primary_department_id:
                String(form.get("primary_department_id") || "") || null,
            }
          : {}),
      });
      onUpdated();
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "用户资料保存失败",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function toggleFreeze() {
    const nextActive = !user.is_active;
    const confirmText = nextActive
      ? `确认解冻账号「${user.display_name}」？解冻后该账号可重新登录系统。`
      : `确认冻结账号「${user.display_name}」？冻结后该账号将无法登录系统。`;
    if (!window.confirm(confirmText)) return;
    setFreezeBusy(true);
    setError("");
    try {
      await api.users.update(user.id, {
        revision: user.revision,
        is_active: nextActive,
      });
      onUpdated();
    } catch (caught) {
      setError(
        caught instanceof ApiClientError
          ? caught.message
          : nextActive
            ? "解冻账号失败"
            : "冻结账号失败",
      );
    } finally {
      setFreezeBusy(false);
    }
  }

  return (
    <Modal title="编辑用户资料" eyebrow="EDIT USER" onClose={onClose}>
      <form className="modal-form" onSubmit={submit}>
        <label className="field">
          <span>登录名</span>
          <input value={user.login_name} readOnly />
          <small className="field-hint">登录名建立后不可修改。</small>
        </label>
        <label className="field">
          <span>显示名称 *</span>
          <input
            name="display_name"
            defaultValue={user.display_name}
            required
            autoFocus
          />
          <small className="field-hint">
            显示名称全系统唯一，修改后用户可用新名称登录。
          </small>
        </label>
        <label className="field">
          <span>角色</span>
          <select name="role" defaultValue={user.role}>
            <option value="member">团队成员</option>
            <option value="team_leader">团队负责人</option>
            {canManageSystemAdmins ? (
              <option value="system_admin">系统管理员</option>
            ) : null}
          </select>
          <small className="field-hint">
            “团队负责人”和“系统管理员”都可以成为其他用户的直属 Leader。
          </small>
        </label>
        <label className="field">
          <span>直属 Leader</span>
          <select name="leader_id" defaultValue={user.leader_id ?? ""}>
            <option value="">暂不指定</option>
            {leaderCandidates.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {candidate.display_name}
              </option>
            ))}
          </select>
          <small className="field-hint">
            {leaderCandidates.length
              ? "周报正式提交时会发送给这里指定的负责人。"
              : "当前没有可用负责人，请先把一个已有用户的角色改为“团队负责人”或“系统管理员”并保存。"}
          </small>
        </label>
        {departments ? (
          <label className="field">
            <span>主部门</span>
            <select
              name="primary_department_id"
              defaultValue={user.primary_department_id ?? ""}
            >
              <option value="">未分配</option>
              {activeDepartments.map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name}
                </option>
              ))}
              {currentDepartmentMissing && user.primary_department_id ? (
                <option value={user.primary_department_id}>
                  {departments.find(
                    (department) =>
                      department.id === user.primary_department_id,
                  )?.name ?? "原部门"}
                  （已停用）
                </option>
              ) : null}
            </select>
            <small className="field-hint">
              主部门决定用户在部门工作和作战台中的归属；变更主部门有安全校验，失败时会提示原因。
            </small>
          </label>
        ) : null}
        <InlineNotice>
          修改角色和直属 Leader 会进入审计日志。已有直属成员的团队负责人不能直接降级。
        </InlineNotice>
        <div className="user-freeze-row">
          <span>
            账号状态：
            <strong className={user.is_active ? "" : "is-frozen"}>
              {user.is_active ? "在用" : "已冻结"}
            </strong>
          </span>
          {canFreeze ? (
            <button
              type="button"
              className="secondary-button"
              disabled={freezeBusy || submitting}
              onClick={() => void toggleFreeze()}
            >
              {freezeBusy
                ? "处理中…"
                : user.is_active
                  ? "冻结账号"
                  : "解冻账号"}
            </button>
          ) : (
            <small className="field-hint">
              {user.id === currentUserId
                ? "不能冻结自己的账号"
                : "仅超级管理员可冻结系统管理员"}
            </small>
          )}
        </div>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" disabled={submitting}>
            {submitting ? "正在保存…" : "保存资料"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

const PERMISSION_DEPENDENCIES: Partial<
  Record<PermissionKey, PermissionKey[]>
> = {
  "dashboard.opportunity.progress": ["dashboard.opportunity.view"],
  "dashboard.opportunity.create": ["dashboard.opportunity.progress"],
  "dashboard.team_summary.generate": [
    "dashboard.work.view",
    "weekly_reports.view",
  ],
  "projects.edit": ["projects.view"],
  "projects.create": ["projects.edit"],
  "departments.manage": ["departments.view"],
  "department_works.edit": [
    "department_works.view",
    "departments.view",
  ],
  "department_works.create": ["department_works.edit"],
  "tasks.edit": ["tasks.view"],
  "tasks.create": ["tasks.edit"],
  "tasks.view": [
    "projects.view",
    "department_works.view",
    "departments.view",
  ],
  "work_records.manage": ["work_records.view"],
  "weekly_reports.manage": ["weekly_reports.view"],
};

function permissionClosure(permission: PermissionKey): Set<PermissionKey> {
  const result = new Set<PermissionKey>();
  const pending = [permission];
  while (pending.length) {
    const current = pending.pop();
    if (!current || result.has(current)) continue;
    result.add(current);
    pending.push(...(PERMISSION_DEPENDENCIES[current] ?? []));
  }
  return result;
}

function PermissionModal({
  user,
  actorRole,
  hasDirectReports,
  onClose,
  onSaved,
}: {
  user: User;
  actorRole: UserRole;
  hasDirectReports: boolean;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [catalog, setCatalog] = useState<PermissionDefinition[]>([]);
  const [details, setDetails] = useState<UserPermissions | null>(null);
  const [selected, setSelected] = useState<Set<PermissionKey>>(new Set());
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.users.permissionCatalog(),
      api.users.permissions(user.id),
    ])
      .then(([definitions, current]) => {
        if (cancelled) return;
        setCatalog(definitions);
        setDetails(current);
        setSelected(new Set(current.effective_permissions));
      })
      .catch((caught) => {
        if (cancelled) return;
        setError(
          caught instanceof ApiClientError
            ? caught.message
            : "用户权限读取失败",
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [user.id]);

  const groups = catalog.reduce<
    Array<{ label: string; permissions: PermissionDefinition[] }>
  >((result, permission) => {
    const existing = result.find((group) => group.label === permission.group_label);
    if (existing) {
      existing.permissions.push(permission);
    } else {
      result.push({
        label: permission.group_label,
        permissions: [permission],
      });
    }
    return result;
  }, []);

  function toggle(permission: PermissionKey, checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) {
        for (const implied of permissionClosure(permission)) next.add(implied);
      } else {
        next.delete(permission);
        let changed = true;
        while (changed) {
          changed = false;
          for (const selectedPermission of Array.from(next)) {
            if (permissionClosure(selectedPermission).has(permission)) {
              next.delete(selectedPermission);
              changed = true;
            }
          }
        }
      }
      return next;
    });
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!details) return;
    setSubmitting(true);
    setError("");
    try {
      await api.users.updatePermissions(
        user.id,
        details.revision,
        Array.from(selected),
      );
      await onSaved();
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "用户权限保存失败",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title={`配置权限 · ${user.display_name}`}
      eyebrow="EXPLICIT ACCESS"
      onClose={onClose}
      wide
    >
      <form className="modal-form permission-modal-form" onSubmit={submit}>
        <InlineNotice>
          权限按层级递增：勾选较高权限会同步勾选其查看和编辑前置权限；取消低级权限会同步取消依赖它的高级权限。
        </InlineNotice>
        {actorRole === "system_admin" ? (
          <InlineNotice tone="warning">
            系统管理员只能调整业务权限和作战台视图；灰色的系统级权限只能由超级管理员配置。
          </InlineNotice>
        ) : null}
        {loading ? (
          <div className="list-loading">
            <i />
            <span>正在读取权限…</span>
          </div>
        ) : (
          <div className="permission-groups">
            {groups.map((group) => (
              <section key={group.label}>
                <header>
                  <h3>{group.label}</h3>
                  <span>
                    {
                      group.permissions.filter((permission) =>
                        selected.has(permission.key),
                      ).length
                    }
                    /{group.permissions.length}
                  </span>
                </header>
                <div>
                  {group.permissions.map((permission) => {
                    const roleAssignable =
                      actorRole === "super_admin" ||
                      permission.system_admin_assignable;
                    const teamScopeEligible =
                      !permission.requires_team_scope ||
                      (["team_leader", "system_admin"].includes(user.role) &&
                        hasDirectReports);
                    const assignable = roleAssignable && teamScopeEligible;
                    return (
                      <label
                        className={`permission-option${
                          assignable ? "" : " locked"
                        }`}
                        key={permission.key}
                      >
                        <input
                          type="checkbox"
                          checked={selected.has(permission.key)}
                          disabled={!assignable}
                          onChange={(event) =>
                            toggle(permission.key, event.target.checked)
                          }
                        />
                        <span>
                          <strong>{permission.label}</strong>
                          <small>{permission.description}</small>
                        </span>
                        {!roleAssignable ? (
                          <em>仅超级管理员</em>
                        ) : !teamScopeEligible ? (
                          <em>需团队负责人及直属成员</em>
                        ) : null}
                      </label>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
        )}
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button
            className="primary-button"
            disabled={loading || submitting || !details}
          >
            {submitting ? "正在保存…" : "保存权限"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function TagCreateModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSubmitting(true);
    setError("");
    try {
      await api.tags.create({
        name: String(form.get("name")),
        description: String(form.get("description") ?? ""),
        color: String(form.get("color") ?? ""),
      });
      onCreated();
    } catch (caught) {
      setError(caught instanceof ApiClientError ? caught.message : "标签创建失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title="创建项目标签" eyebrow="NEW TAG" onClose={onClose}>
      <form className="modal-form" onSubmit={submit}>
        <label className="field">
          <span>标签名称 *</span>
          <input name="name" required autoFocus />
        </label>
        <label className="field">
          <span>说明</span>
          <textarea name="description" rows={4} />
        </label>
        <label className="field color-field">
          <span>标识颜色</span>
          <input name="color" type="color" defaultValue="#2563eb" />
        </label>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" disabled={submitting}>
            {submitting ? "正在创建…" : "创建标签"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function TagEditModal({
  tag,
  onClose,
  onUpdated,
}: {
  tag: ProjectTag;
  onClose: () => void;
  onUpdated: () => void;
}) {
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const isActive = form.get("is_active") === "on";
    if (
      tag.is_active &&
      !isActive &&
      !window.confirm(`确认停用标签“${tag.name}”？已有项目关联会保留。`)
    ) {
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await api.tags.update(tag.id, {
        revision: tag.revision,
        name: String(form.get("name")),
        description: optionalText(form.get("description")),
        color: optionalText(form.get("color")),
        sort_order: Number(form.get("sort_order")),
        is_active: isActive,
      });
      onUpdated();
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "标签更新失败",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title={`编辑项目标签 · ${tag.name}`} eyebrow="EDIT TAG" onClose={onClose}>
      <form className="modal-form" onSubmit={submit}>
        <label className="field">
          <span>标签名称 *</span>
          <input name="name" defaultValue={tag.name} required autoFocus />
        </label>
        <label className="field">
          <span>说明</span>
          <textarea
            name="description"
            rows={4}
            defaultValue={tag.description ?? ""}
          />
        </label>
        <div className="form-grid">
          <label className="field color-field">
            <span>标识颜色</span>
            <input
              name="color"
              type="color"
              defaultValue={
                /^#[0-9a-f]{6}$/i.test(tag.color ?? "")
                  ? tag.color ?? "#2563eb"
                  : "#2563eb"
              }
            />
          </label>
          <label className="field">
            <span>排序值</span>
            <input
              name="sort_order"
              type="number"
              min="-10000"
              max="10000"
              defaultValue={tag.sort_order}
              required
            />
          </label>
        </div>
        <label className="toggle-filter">
          <input name="is_active" type="checkbox" defaultChecked={tag.is_active} />
          <span />
          启用此标签
        </label>
        <InlineNotice>
          停用后不会出现在新项目的标签选择中，已有项目关联仍会保留。
        </InlineNotice>
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

function DepartmentMembersModal({
  department,
  users,
  onClose,
}: {
  department: Department;
  users: User[];
  onClose: () => void;
}) {
  const members = users
    .filter((user) => user.primary_department_id === department.id)
    .sort((a, b) => a.display_name.localeCompare(b.display_name, "zh-CN"));
  const activeCount = members.filter((user) => user.is_active).length;

  return (
    <Modal
      title={`部门成员 · ${department.name}`}
      eyebrow="DEPARTMENT MEMBERS"
      onClose={onClose}
      wide
    >
      <div className="department-members-panel">
        <p className="department-members-meta">
          主部门归属成员 <strong>{members.length}</strong> 人，其中在用{" "}
          <strong>{activeCount}</strong> 人（含已停用账号）。
        </p>
        {members.length ? (
          <div className="department-members-list">
            {members.map((user) => (
              <article key={user.id}>
                <AvatarImage
                  avatarKey={user.avatar_key}
                  displayName={user.display_name}
                  className="avatar-large"
                  decorative
                />
                <div>
                  <h3>{user.display_name}</h3>
                  <p>@{user.login_name}</p>
                </div>
                <span className={`role-pill role-${user.role}`}>
                  {roleLabel(user.role)}
                </span>
                <small>
                  {user.leader_id
                    ? `直属：${
                        users.find((item) => item.id === user.leader_id)
                          ?.display_name ?? "未知"
                      }`
                    : "直属：未指定"}
                </small>
                <span className={`tag${user.is_active ? "" : " tag-muted"}`}>
                  {user.is_active ? "在用" : "已停用"}
                </span>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="暂无成员"
            description="尚未有用户的主部门归属到本部门。"
          />
        )}
      </div>
    </Modal>
  );
}

function DepartmentCreateModal({
  candidates,
  onClose,
  onCreated,
}: {
  candidates: UserCandidate[];
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const leaderCandidates = candidates;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSubmitting(true);
    setError("");
    try {
      await api.departments.create({
        name: String(form.get("name")).trim(),
        leader_id: String(form.get("leader_id") || "") || null,
      });
      await onCreated();
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "部门创建失败",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title="创建部门" eyebrow="NEW DEPARTMENT" onClose={onClose}>
      <form className="modal-form" onSubmit={submit}>
        <label className="field">
          <span>部门名称 *</span>
          <input name="name" required autoFocus placeholder="例如 交付一部" />
          <small className="field-hint">部门名称全系统唯一。</small>
        </label>
        <label className="field">
          <span>负责人</span>
          <select name="leader_id" defaultValue="">
            <option value="">暂不指定</option>
            {leaderCandidates.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {candidate.display_name}
              </option>
            ))}
          </select>
          <small className="field-hint">
            {leaderCandidates.length
              ? "同一用户可担任多个部门的负责人；若其尚无主部门，创建时会顺带写入该部门。"
              : "当前没有可指定的用户，可先创建部门再在编辑中指定负责人。"}
          </small>
        </label>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" disabled={submitting}>
            {submitting ? "正在创建…" : "创建部门"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function DepartmentEditModal({
  department,
  candidates,
  onClose,
  onUpdated,
}: {
  department: Department;
  candidates: UserCandidate[];
  onClose: () => void;
  onUpdated: () => Promise<void>;
}) {
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const leaderCandidates = candidates;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const isActive = form.get("is_active") === "on";
    if (
      department.is_active &&
      !isActive &&
      !window.confirm(
        `确认停用部门“${department.name}”？停用前需确保部门内没有成员和未归档的部门工作。`,
      )
    ) {
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await api.departments.update(department.id, {
        revision: department.revision,
        name: String(form.get("name")).trim(),
        leader_id: String(form.get("leader_id") || "") || null,
        is_active: isActive,
      });
      await onUpdated();
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "部门保存失败",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title={`编辑部门 · ${department.name}`}
      eyebrow="EDIT DEPARTMENT"
      onClose={onClose}
    >
      <form className="modal-form" onSubmit={submit}>
        <label className="field">
          <span>部门名称 *</span>
          <input name="name" defaultValue={department.name} required autoFocus />
        </label>
        <label className="field">
          <span>负责人</span>
          <select name="leader_id" defaultValue={department.leader_id ?? ""}>
            <option value="">暂不指定</option>
            {leaderCandidates.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {candidate.display_name}
              </option>
            ))}
          </select>
          <small className="field-hint">
            同一用户可担任多个部门的负责人，不必先把主部门改到本部门。
          </small>
        </label>
        <label className="toggle-filter">
          <input
            name="is_active"
            type="checkbox"
            defaultChecked={department.is_active}
          />
          <span />
          启用此部门
        </label>
        <InlineNotice>
          停用后不会出现在新的部门工作选择中；有成员或未归档部门工作时无法停用。
        </InlineNotice>
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

function optionalText(value: FormDataEntryValue | null) {
  const text = String(value ?? "").trim();
  return text || null;
}

function roleLabel(role: string) {
  return (
    {
      member: "团队成员",
      team_leader: "团队负责人",
      system_admin: "系统管理员",
      super_admin: "超级管理员",
    }[role] ?? role
  );
}

const INITIAL_PASSWORD_CHARACTER_SETS = [
  "ABCDEFGHJKLMNPQRSTUVWXYZ",
  "abcdefghijkmnopqrstuvwxyz",
  "23456789",
  "!@#$%^&*()-_=+?",
] as const;

function generateStrongInitialPassword(length = 20) {
  const allCharacters = INITIAL_PASSWORD_CHARACTER_SETS.join("");
  const characters = INITIAL_PASSWORD_CHARACTER_SETS.map(
    (characterSet) => characterSet[secureRandomIndex(characterSet.length)],
  );

  while (characters.length < length) {
    characters.push(allCharacters[secureRandomIndex(allCharacters.length)]);
  }
  for (let index = characters.length - 1; index > 0; index -= 1) {
    const swapIndex = secureRandomIndex(index + 1);
    [characters[index], characters[swapIndex]] = [
      characters[swapIndex],
      characters[index],
    ];
  }
  return characters.join("");
}

function secureRandomIndex(limit: number) {
  const range = 0x1_0000_0000;
  const maximumAcceptedValue = Math.floor(range / limit) * limit;
  const randomValue = new Uint32Array(1);
  do {
    crypto.getRandomValues(randomValue);
  } while (randomValue[0] >= maximumAcceptedValue);
  return randomValue[0] % limit;
}
