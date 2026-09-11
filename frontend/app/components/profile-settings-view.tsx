"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiClientError, setCsrfToken } from "../api";
import type { AuthContext, AvatarOption } from "../types";
import { AvatarImage, AvatarOptionPreview } from "./avatar";
import { Shield } from "./icons";
import { InlineNotice, Modal } from "./ui";

export function ProfileSettingsView({
  context,
  onContextChange,
}: {
  context: AuthContext;
  onContextChange: (context: AuthContext) => void;
}) {
  const [avatarOptions, setAvatarOptions] = useState<AvatarOption[]>([]);
  const [selectedAvatar, setSelectedAvatar] = useState<string | null>(
    context.user.avatar_key,
  );
  const [avatarError, setAvatarError] = useState("");
  const [avatarMessage, setAvatarMessage] = useState("");
  const [avatarBusy, setAvatarBusy] = useState(false);
  const [avatarModalOpen, setAvatarModalOpen] = useState(false);
  const [activeStyle, setActiveStyle] = useState("");

  useEffect(() => {
    api.profile
      .avatars()
      .then((options) => {
        setAvatarOptions(options);
        setActiveStyle(
          options.find((option) => option.id === context.user.avatar_key)
            ?.style ??
            options[0]?.style ??
            "",
        );
      })
      .catch((caught) =>
        setAvatarError(
          caught instanceof ApiClientError
            ? caught.message
            : "头像列表加载失败",
        ),
      );
  }, [context.user.avatar_key]);

  async function saveAvatar() {
    setAvatarBusy(true);
    setAvatarError("");
    setAvatarMessage("");
    try {
      const user = await api.profile.updateAvatar(
        context.user.revision,
        selectedAvatar,
      );
      onContextChange({ ...context, user });
      setAvatarMessage("头像已更新。");
      setAvatarModalOpen(false);
    } catch (caught) {
      setAvatarError(
        caught instanceof ApiClientError ? caught.message : "头像保存失败",
      );
    } finally {
      setAvatarBusy(false);
    }
  }

  const avatarStyles = avatarOptions.filter(
    (option, index, options) =>
      options.findIndex((candidate) => candidate.style === option.style) ===
      index,
  );
  const selectedOption = avatarOptions.find(
    (option) => option.id === selectedAvatar,
  );
  const currentOption = avatarOptions.find(
    (option) => option.id === context.user.avatar_key,
  );

  function openAvatarModal() {
    setSelectedAvatar(context.user.avatar_key);
    setActiveStyle(
      currentOption?.style ?? avatarOptions[0]?.style ?? "",
    );
    setAvatarError("");
    setAvatarModalOpen(true);
  }

  return (
    <div className="view-shell profile-settings-view">
      <header className="view-header">
        <div>
          <p className="eyebrow">PERSONAL SETTINGS</p>
          <h1>个人设置</h1>
          <p>管理自己的登录密码与系统头像，不影响角色和汇报关系。</p>
        </div>
      </header>

      <section className="profile-identity-card">
        <AvatarImage
          avatarKey={context.user.avatar_key}
          displayName={context.user.display_name}
          className="profile-current-avatar"
        />
        <div>
          <p className="eyebrow">SIGNED IN AS</p>
          <h2>{context.user.display_name}</h2>
          <p>@{context.user.login_name}</p>
        </div>
        <span>{roleLabel(context.user.role)}</span>
      </section>

      <div className="profile-settings-grid">
        <section className="settings-card avatar-settings-card">
          <header>
            <div>
              <p className="eyebrow">AVATAR</p>
              <h2>个人头像</h2>
              <p>当前头像会用于侧栏和人员目录，可随时更换。</p>
            </div>
            <AvatarImage
              avatarKey={context.user.avatar_key}
              displayName={context.user.display_name}
              className="settings-avatar-preview"
            />
          </header>
          <div className="avatar-setting-summary">
            <div>
              <strong>{currentOption?.label ?? "姓名首字头像"}</strong>
              <p>
                系统提供 {avatarStyles.length || 7} 套风格、
                {avatarOptions.length || 56} 张预置头像，不支持上传和外部图片。
              </p>
            </div>
            <button
              className="secondary-button"
              type="button"
              onClick={openAvatarModal}
            >
              更换头像
            </button>
          </div>
          {avatarError ? (
            <InlineNotice tone="error">{avatarError}</InlineNotice>
          ) : null}
          {avatarMessage ? <InlineNotice>{avatarMessage}</InlineNotice> : null}
        </section>

        <PasswordSettingsCard onContextChange={onContextChange} />
      </div>

      {avatarModalOpen ? (
        <Modal
          title="选择系统头像"
          eyebrow="AVATAR LIBRARY"
          wide
          onClose={() => setAvatarModalOpen(false)}
        >
          <div className="avatar-modal-body">
            <section className="avatar-modal-summary">
              <AvatarImage
                avatarKey={selectedAvatar}
                displayName={context.user.display_name}
                className="avatar-modal-preview"
              />
              <div>
                <strong>{selectedOption?.label ?? "姓名首字头像"}</strong>
                <p>头像均经过统一尺寸和压缩处理，并针对圆形显示保留安全区域。</p>
              </div>
              <button
                type="button"
                className="text-button"
                onClick={() => setSelectedAvatar(null)}
              >
                恢复姓名首字
              </button>
            </section>

            <nav className="avatar-style-tabs" aria-label="头像风格">
              {avatarStyles.map((style) => (
                <button
                  type="button"
                  className={activeStyle === style.style ? "active" : ""}
                  key={style.style}
                  onClick={() => setActiveStyle(style.style)}
                >
                  {style.style_label}
                  <span>8</span>
                </button>
              ))}
            </nav>

            <div className="avatar-picker" role="radiogroup" aria-label="系统头像">
              {avatarOptions
                .filter((option) => option.style === activeStyle)
                .map((option) => (
                  <button
                    type="button"
                    role="radio"
                    aria-checked={selectedAvatar === option.id}
                    className={selectedAvatar === option.id ? "active" : ""}
                    key={option.id}
                    onClick={() => setSelectedAvatar(option.id)}
                  >
                    <AvatarOptionPreview
                      avatarKey={option.id}
                      label={option.label}
                    />
                    <span>形象 {String(option.character).padStart(2, "0")}</span>
                  </button>
                ))}
            </div>
            {!avatarOptions.length && !avatarError ? (
              <p className="settings-loading">正在读取系统头像…</p>
            ) : null}
            {avatarError ? (
              <InlineNotice tone="error">{avatarError}</InlineNotice>
            ) : null}
            <footer className="modal-actions">
              <button
                type="button"
                className="secondary-button"
                onClick={() => setAvatarModalOpen(false)}
              >
                取消
              </button>
              <button
                className="primary-button"
                type="button"
                disabled={
                  avatarBusy || selectedAvatar === context.user.avatar_key
                }
                onClick={saveAvatar}
              >
                {avatarBusy ? "正在保存…" : "使用这个头像"}
              </button>
            </footer>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}

function PasswordSettingsCard({
  onContextChange,
}: {
  onContextChange: (context: AuthContext) => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmedPassword, setConfirmedPassword] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (newPassword !== confirmedPassword) {
      setError("两次输入的新密码不一致");
      return;
    }
    setSubmitting(true);
    setError("");
    setMessage("");
    try {
      await api.auth.changePassword(currentPassword, newPassword);
      const refreshed = await api.auth.me();
      setCsrfToken(refreshed.csrf_token);
      onContextChange(refreshed);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmedPassword("");
      setMessage("密码已修改，其他已登录会话已失效。");
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "密码修改失败",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="settings-card password-settings-card">
      <header>
        <div>
          <p className="eyebrow">PASSWORD</p>
          <h2>修改密码</h2>
          <p>所有用户都可以修改自己的密码，保存后会注销其他登录会话。</p>
        </div>
        <span className="security-mark" aria-hidden="true">
          <Shield size={24} />
        </span>
      </header>
      <form onSubmit={submit}>
        <label className="field">
          <span>当前密码</span>
          <input
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            required
          />
        </label>
        <label className="field">
          <span>新密码</span>
          <input
            type="password"
            minLength={5}
            autoComplete="new-password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            required
          />
          <small className="field-hint">唯一限制：长度必须大于 4 位。</small>
        </label>
        <label className="field">
          <span>确认新密码</span>
          <input
            type="password"
            minLength={5}
            autoComplete="new-password"
            value={confirmedPassword}
            onChange={(event) => setConfirmedPassword(event.target.value)}
            required
          />
        </label>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        {message ? <InlineNotice>{message}</InlineNotice> : null}
        <button className="primary-button" disabled={submitting}>
          {submitting ? "正在更新…" : "更新密码"}
        </button>
      </form>
    </section>
  );
}

function roleLabel(role: string) {
  return (
    {
      member: "团队成员",
      team_leader: "团队负责人",
      system_admin: "系统管理员",
      super_admin: "系统维护",
    }[role] ?? role
  );
}
