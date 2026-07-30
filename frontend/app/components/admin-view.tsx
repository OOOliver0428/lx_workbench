"use client";

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiClientError } from "../api";
import type {
  AuditEvent,
  AuthContext,
  PermissionDefinition,
  PermissionKey,
  ProjectTag,
  User,
  UserPermissions,
  UserRole,
} from "../types";
import { AIConfigPanel } from "./ai-config-panel";
import { AvatarImage } from "./avatar";
import { EmptyState, InlineNotice, Modal } from "./ui";

type AdminTab = "users" | "tags" | "ai" | "audit";

export function AdminView({ context }: { context: AuthContext }) {
  const permissions = context.permissions ?? [];
  const canManagePermissions = ["system_admin", "super_admin"].includes(
    context.user.role,
  );
  const canManageUsers = permissions.includes("settings.users.manage");
  const canManageTags = permissions.includes("settings.tags.manage");
  const canManageAi = permissions.includes("settings.ai.manage");
  const canViewAudit = permissions.includes("settings.audit.view");
  const showUsers = canManagePermissions || canManageUsers;
  const [users, setUsers] = useState<User[]>([]);
  const [tags, setTags] = useState<ProjectTag[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [tab, setTab] = useState<AdminTab>(
    showUsers
      ? "users"
      : canManageTags
        ? "tags"
        : canManageAi
          ? "ai"
          : "audit",
  );
  const [createUserOpen, setCreateUserOpen] = useState(false);
  const [createTagOpen, setCreateTagOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [permissionUser, setPermissionUser] = useState<User | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [userRows, tagRows, auditRows] = await Promise.all([
        showUsers ? api.users.list() : Promise.resolve([]),
        canManageTags ? api.tags.list() : Promise.resolve([]),
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
  }, [canManageTags, canViewAudit, showUsers]);

  useEffect(() => {
    const timeout = window.setTimeout(load, 0);
    return () => window.clearTimeout(timeout);
  }, [load]);

  return (
    <div className="view-shell">
      <header className="view-header">
        <div>
          <p className="eyebrow">SYSTEM SETTINGS</p>
          <h1>系统设置</h1>
          <p>维护本地用户、权限、项目标签、大模型接入与审计记录。</p>
        </div>
        {(tab === "users" && canManageUsers) ||
        (tab === "tags" && canManageTags) ? (
          <button
            className="primary-button"
            onClick={() =>
              tab === "users" ? setCreateUserOpen(true) : setCreateTagOpen(true)
            }
          >
            <span>＋</span> {tab === "users" ? "创建用户" : "创建标签"}
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
                <small>{user.is_active ? "账号正常" : "账号停用"}</small>
                <div className="user-card-management">
                  <span>
                    直属 Leader
                    <strong>
                      {users.find((candidate) => candidate.id === user.leader_id)
                        ?.display_name ?? "未指定"}
                    </strong>
                  </span>
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
              <small>{tag.is_active ? "使用中" : "已停用"}</small>
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
          onClose={() => setCreateUserOpen(false)}
          onCreated={async () => {
            await load();
          }}
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
      {editingUser && canManageUsers ? (
        <UserEditModal
          user={editingUser}
          users={users}
          canManageSystemAdmins={context.user.role === "super_admin"}
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
  onClose,
  onCreated,
}: {
  canCreateSystemAdmin: boolean;
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
              ⚄
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
  canManageSystemAdmins,
  onClose,
  onUpdated,
}: {
  user: User;
  users: User[];
  canManageSystemAdmins: boolean;
  onClose: () => void;
  onUpdated: () => void;
}) {
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const leaderCandidates = users.filter(
    (candidate) =>
      candidate.id !== user.id &&
      ["team_leader", "system_admin"].includes(candidate.role) &&
      candidate.is_active,
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
        <InlineNotice>
          修改角色和直属 Leader 会进入审计日志。已有直属成员的团队负责人不能直接降级。
        </InlineNotice>
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

function PermissionModal({
  user,
  actorRole,
  onClose,
  onSaved,
}: {
  user: User;
  actorRole: UserRole;
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
        setSelected(new Set(current.assigned_permissions));
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
      if (checked) next.add(permission);
      else next.delete(permission);
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
          角色不再自动附带业务功能。勾选结果会同时控制页面、按钮和后端接口；管理类权限会自动包含对应的查看权限。
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
                    const assignable =
                      actorRole === "super_admin" ||
                      permission.system_admin_assignable;
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
                        {!assignable ? <em>仅超级管理员</em> : null}
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
