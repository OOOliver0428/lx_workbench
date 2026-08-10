"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { api, ApiClientError } from "../api";
import type {
  AIChatResult,
  AIStatus,
  AuthContext,
  PermissionKey,
  WeeklyReport,
} from "../types";
import { createClientMessageId } from "../client-id";
import { InlineNotice } from "./ui";
import { AvatarImage } from "./avatar";
import {
  ChevronLeft,
  ChevronRight,
  Close,
  Logout,
  Sparkle,
} from "./icons";

export type WorkspaceView =
  | "dashboard"
  | "projects"
  | "department-works"
  | "tasks"
  | "records"
  | "reports"
  | "profile"
  | "admin";

const navigation: Array<{
  id: WorkspaceView;
  label: string;
  index: string;
  description: string;
}> = [
  { id: "dashboard", label: "作战台", index: "01", description: "进展、产出与节奏" },
  { id: "projects", label: "项目", index: "02", description: "主数据与协作" },
  {
    id: "department-works",
    label: "部门工作",
    index: "03",
    description: "部门事项与协作",
  },
  { id: "tasks", label: "任务", index: "04", description: "推进与交付" },
  { id: "records", label: "工作记录", index: "05", description: "个人工作沉淀" },
  { id: "reports", label: "周报", index: "06", description: "生成、提交与审阅" },
  {
    id: "profile",
    label: "个人设置",
    index: "07",
    description: "头像与密码",
  },
  {
    id: "admin",
    label: "系统设置",
    index: "08",
    description: "用户、标签与模型",
  },
];

const dashboardPermissions: PermissionKey[] = [
  "dashboard.opportunity.view",
  "dashboard.work.view",
  "dashboard.overview.view",
];

const settingsPermissions: PermissionKey[] = [
  "settings.users.manage",
  "settings.tags.manage",
  "settings.ai.manage",
  "settings.audit.view",
];

export function canAccessWorkspaceView(
  context: AuthContext,
  view: WorkspaceView,
) {
  const permissions = context.permissions ?? [];
  const has = (permission: PermissionKey) =>
    permissions.includes(permission);
  if (view === "profile") return true;
  if (view === "dashboard") return dashboardPermissions.some(has);
  if (view === "projects") return has("projects.view");
  if (view === "department-works") return has("department_works.view");
  if (view === "tasks") return has("tasks.view");
  if (view === "records") return has("work_records.view");
  if (view === "reports") return has("weekly_reports.view");
  return (
    ["system_admin", "super_admin"].includes(context.user.role) ||
    settingsPermissions.some(has)
  );
}

export function defaultWorkspaceView(context: AuthContext): WorkspaceView {
  return (
    navigation.find((item) => canAccessWorkspaceView(context, item.id))?.id ??
    "profile"
  );
}

export function AppShell({
  context,
  activeView,
  onViewChange,
  onLogout,
  logoutError,
  logoutPending,
  children,
}: {
  context: AuthContext;
  activeView: WorkspaceView;
  onViewChange: (view: WorkspaceView) => void;
  onLogout: () => void;
  logoutError: string;
  logoutPending: boolean;
  children: ReactNode;
}) {
  const [aiOpen, setAiOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const navRef = useRef<HTMLElement | null>(null);
  const [navGlider, setNavGlider] = useState<{
    top: number;
    height: number;
  } | null>(null);
  const permissions = context.permissions ?? [];
  const canUseAi = permissions.includes("ai.use");
  const canManageWeeklyReports = permissions.includes(
    "weekly_reports.manage",
  );
  const visibleNavigation = navigation.filter((item) =>
    canAccessWorkspaceView(context, item.id),
  );

  useLayoutEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    const measure = () => {
      const activeButton = nav.querySelector<HTMLElement>("button.active");
      if (!activeButton) {
        setNavGlider(null);
        return;
      }
      setNavGlider({
        top: activeButton.offsetTop,
        height: activeButton.offsetHeight,
      });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(nav);
    return () => observer.disconnect();
  }, [activeView, sidebarCollapsed, visibleNavigation.length]);

  function confirmLogout() {
    if (window.confirm("确认退出当前账号吗？")) {
      onLogout();
    }
  }

  return (
    <div className={`app-frame${sidebarCollapsed ? " sidebar-collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="sidebar-head">
          <div className="brand-lockup">
            <span className="brand-symbol">
              <i />
              <i />
              <i />
            </span>
            <span>
              <strong>协作工作台</strong>
              <small>赋能售前和解决方案</small>
            </span>
          </div>
          <button
            type="button"
            className="sidebar-toggle"
            onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
            aria-label={sidebarCollapsed ? "展开左侧导航栏" : "收起左侧导航栏"}
            aria-pressed={sidebarCollapsed}
            title={sidebarCollapsed ? "展开导航栏" : "收起导航栏"}
          >
            <span aria-hidden="true">
              {sidebarCollapsed ? (
                <ChevronRight size={15} />
              ) : (
                <ChevronLeft size={15} />
              )}
            </span>
          </button>
        </div>
        <nav className="primary-nav" aria-label="主导航" ref={navRef}>
          <p className="nav-caption">工作空间</p>
          {navGlider ? (
            <span
              className="nav-glider"
              aria-hidden="true"
              style={{
                height: navGlider.height,
                transform: `translateY(${navGlider.top}px)`,
              }}
            />
          ) : null}
          {visibleNavigation.map((item) => (
            <button
              type="button"
              key={item.id}
              className={activeView === item.id ? "active" : ""}
              onClick={() => onViewChange(item.id)}
              aria-current={activeView === item.id ? "page" : undefined}
              aria-label={item.label}
              title={`${item.label} · ${item.description}`}
            >
              <span className="nav-index">{item.index}</span>
              <span>
                <strong>{item.label}</strong>
                <small>{item.description}</small>
              </span>
              <i className="nav-arrow">
                <ChevronRight size={15} />
              </i>
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          {canUseAi || canManageWeeklyReports ? (
            <button
              type="button"
              className="ai-entry"
              onClick={() => setAiOpen(true)}
              aria-label="打开 AI 助手"
              title="打开 AI 助手"
            >
              <span className="ai-orbit" aria-hidden="true">
                <Sparkle size={16} />
              </span>
              <span>
                <strong>AI 助手</strong>
                <small>项目与工作智能辅助</small>
              </span>
            </button>
          ) : null}
          <div className="account-summary">
            <button
              type="button"
              className="account-profile-button"
              onClick={() => onViewChange("profile")}
              aria-label="打开个人设置"
              title="个人设置"
            >
              <AvatarImage
                avatarKey={context.user.avatar_key}
                displayName={context.user.display_name}
                decorative
              />
              <span>
                <strong>{context.user.display_name}</strong>
                <small>{roleLabel(context.user.role)}</small>
              </span>
            </button>
            <button
              className="account-logout-button"
              onClick={confirmLogout}
              disabled={logoutPending}
              aria-busy={logoutPending}
              aria-label="退出登录"
              title="退出登录"
            >
              <Logout size={15} />
            </button>
          </div>
        </div>
      </aside>
      <div className="workspace-main">
        {logoutError ? (
          <div className="workspace-alert">
            <InlineNotice tone="error">{logoutError}</InlineNotice>
          </div>
        ) : null}
        {children}
      </div>
      {aiOpen ? (
        <AIDrawer
          canUseAi={canUseAi}
          canManageWeeklyReports={canManageWeeklyReports}
          onClose={() => setAiOpen(false)}
        />
      ) : null}
    </div>
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

function AIDrawer({
  canUseAi,
  canManageWeeklyReports,
  onClose,
}: {
  canUseAi: boolean;
  canManageWeeklyReports: boolean;
  onClose: () => void;
}) {
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState<
    Array<{
      id: string;
      role: "user" | "assistant";
      content: string;
      model?: string;
      totalTokens?: number;
    }>
  >([]);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [weekStart, setWeekStart] = useState("");
  const [weekEnd, setWeekEnd] = useState("");
  const [weeklyReport, setWeeklyReport] = useState<WeeklyReport | null>(null);
  const [reportContent, setReportContent] = useState("");
  const [reportBusy, setReportBusy] = useState(false);
  const [reportMessage, setReportMessage] = useState("");
  const conversationEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    Promise.all([
      api.ai.status(),
      canManageWeeklyReports
        ? api.weeklyReports.current()
        : Promise.resolve(null),
    ])
      .then(([serviceStatus, current]) => {
        setStatus(serviceStatus);
        if (current) {
          setWeekStart(current.week_start);
          setWeekEnd(current.week_end);
          setWeeklyReport(current.report);
          setReportContent(current.report?.content ?? "");
        }
      })
      .catch(() => setError("无法读取 AI 服务或本周周报状态"));
  }, [canManageWeeklyReports]);

  useEffect(() => {
    conversationEndRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end",
    });
  }, [messages, submitting]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const question = prompt.trim();
    if (!question || submitting) return;
    const questionId = createClientMessageId();
    setPrompt("");
    setMessages((current) => [
      ...current,
      {
        id: questionId,
        role: "user",
        content: question,
      },
    ]);
    setSubmitting(true);
    setError("");
    try {
      const result: AIChatResult = await api.ai.chat(question, questionId);
      setMessages((current) => [
        ...current,
        {
          id: `${questionId}-answer`,
          role: "assistant",
          content: result.answer,
          model: result.model,
          totalTokens: result.usage.total_tokens,
        },
      ]);
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "AI 服务暂时不可用",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function generateWeeklyReport() {
    if (
      weeklyReport &&
      reportContent !== weeklyReport.content &&
      !window.confirm("当前有尚未保存的编辑内容，重新生成会丢弃这些内容。是否继续？")
    ) {
      return;
    }
    if (
      weeklyReport?.submitted_content &&
      !window.confirm(
        "重新生成会更新本周草稿，但不会立即覆盖 Leader 已看到的版本。是否继续？",
      )
    ) {
      return;
    }
    setReportBusy(true);
    setReportMessage("");
    setError("");
    try {
      const generated = await api.weeklyReports.generateCurrent();
      setWeeklyReport(generated);
      setReportContent(generated.content);
      setReportMessage("本周周报草稿已生成并保存，可继续编辑。");
    } catch (caught) {
      setError(
        caught instanceof ApiClientError
          ? caught.message
          : "本周周报生成失败",
      );
    } finally {
      setReportBusy(false);
    }
  }

  async function saveWeeklyDraft() {
    if (!weeklyReport || !reportContent.trim()) return weeklyReport;
    const saved = await api.weeklyReports.saveDraft(
      weeklyReport.id,
      weeklyReport.revision,
      reportContent,
    );
    setWeeklyReport(saved);
    setReportContent(saved.content);
    setReportMessage("草稿已保存，Leader 暂时不可见。");
    return saved;
  }

  async function handleSaveWeeklyDraft() {
    setReportBusy(true);
    setReportMessage("");
    setError("");
    try {
      await saveWeeklyDraft();
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "周报草稿保存失败",
      );
    } finally {
      setReportBusy(false);
    }
  }

  async function submitWeeklyReport() {
    if (!weeklyReport || !reportContent.trim()) return;
    const isOverwrite = Boolean(weeklyReport.submitted_content);
    if (
      isOverwrite &&
      !window.confirm(
        "本周已有已提交周报，本次提交会覆盖 Leader 当前看到的版本。是否继续？",
      )
    ) {
      return;
    }
    setReportBusy(true);
    setReportMessage("");
    setError("");
    try {
      let reportToSubmit: WeeklyReport | null = weeklyReport;
      if (reportContent !== weeklyReport.content) {
        reportToSubmit = await saveWeeklyDraft();
      }
      if (!reportToSubmit) return;
      const submittedReport = await api.weeklyReports.submit(
        reportToSubmit.id,
        reportToSubmit.revision,
        isOverwrite,
      );
      setWeeklyReport(submittedReport);
      setReportContent(submittedReport.content);
      setReportMessage(
        isOverwrite
          ? "本周周报已重新提交，Leader 看到的版本已更新。"
          : "本周周报已提交给直属 Leader。",
      );
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "周报提交失败",
      );
    } finally {
      setReportBusy(false);
    }
  }

  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside
        className="ai-drawer"
        onMouseDown={(event) => event.stopPropagation()}
        aria-label="团队 AI 助手"
      >
        <header>
          <div className="ai-title-mark">
            <Sparkle size={16} />
          </div>
          <div>
            <p className="eyebrow">AI COPILOT</p>
            <h2>团队 AI 助手</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="关闭">
            <Close size={16} />
          </button>
        </header>
        <div className="ai-service-status">
          <i className={status?.configured ? "online" : ""} />
          <span>
            {status
              ? `${status.provider} · ${status.model}`
              : "正在检查服务状态…"}
          </span>
        </div>
        <div className="ai-conversation">
          {canUseAi && messages.length === 0 ? (
            <div className="ai-welcome">
              <span>
                <Sparkle size={26} />
              </span>
              <h3>从一个具体问题开始</h3>
              <p>
                可以让我梳理项目目标、拆解下一步，或把工作记录整理成清晰表述。
                本次对话在关闭窗口后清空。
              </p>
              <div className="suggestion-list">
                {[
                  "如何判断两个项目是否应该合并？",
                  "帮我把一段工作描述改得更清晰",
                  "新项目启动时最先确认哪些信息？",
                ].map((text) => (
                  <button key={text} onClick={() => setPrompt(text)}>
                    {text}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {canManageWeeklyReports ? (
          <section className="weekly-report-card">
            <header>
              <div>
                <span className="answer-label">WEEKLY REPORT</span>
                <h3>本周周报</h3>
                <p>
                  {weekStart && weekEnd
                    ? `${weekStart} 至 ${weekEnd}（周一至周日）`
                    : "按自然周生成"}
                </p>
              </div>
              {weeklyReport?.submitted_at ? (
                <span className="weekly-status submitted">
                  已提交 V{weeklyReport.submission_version}
                </span>
              ) : weeklyReport ? (
                <span className="weekly-status">草稿</span>
              ) : null}
            </header>
            {weeklyReport ? (
              <>
                <textarea
                  className="weekly-report-editor"
                  value={reportContent}
                  onChange={(event) => {
                    setReportContent(event.target.value);
                    setReportMessage("");
                  }}
                  rows={16}
                  aria-label="本周周报草稿"
                />
                {weeklyReport.submitted_content &&
                reportContent !== weeklyReport.submitted_content ? (
                  <InlineNotice tone="warning">
                    当前草稿与已提交版本不同；保存草稿不会影响 Leader，重新提交后才会覆盖。
                  </InlineNotice>
                ) : null}
                {reportMessage ? <InlineNotice>{reportMessage}</InlineNotice> : null}
                <div className="weekly-report-actions">
                  <button
                    type="button"
                    className="secondary-button compact"
                    disabled={
                      reportBusy || reportContent === weeklyReport.content
                    }
                    onClick={handleSaveWeeklyDraft}
                  >
                    保存草稿
                  </button>
                  <button
                    type="button"
                    className="secondary-button compact"
                    disabled={reportBusy || !status?.configured}
                    onClick={generateWeeklyReport}
                  >
                    重新生成
                  </button>
                  <button
                    type="button"
                    className="primary-button compact"
                    disabled={reportBusy || !reportContent.trim()}
                    onClick={submitWeeklyReport}
                  >
                    {weeklyReport.submitted_at ? "重新提交" : "提交给 Leader"}
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="weekly-report-explainer">
                  AI 只读取你本周的工作记录；没有本周工作记录的项目不会进入生成上下文。
                  生成结果会作为草稿保存，提交前可以编辑。
                </p>
                <button
                  type="button"
                  className="weekly-generate-button"
                  disabled={reportBusy || !status?.configured}
                  onClick={generateWeeklyReport}
                >
                  {reportBusy ? (
                    "正在生成…"
                  ) : (
                    <>
                      <Sparkle size={14} /> 生成本周周报
                    </>
                  )}
                </button>
              </>
            )}
          </section>
          ) : null}
          {canUseAi && messages.length ? (
            <section
              className="ai-chat-thread"
              aria-label="本次 AI 对话"
              aria-live="polite"
            >
              {messages.map((message) => (
                <article
                  className={`ai-chat-row ai-chat-${message.role}`}
                  key={message.id}
                >
                  {message.role === "assistant" ? (
                    <span className="ai-message-avatar" aria-hidden="true">
                      <Sparkle size={14} />
                    </span>
                  ) : null}
                  <div className="ai-chat-bubble">
                    <span>
                      {message.role === "user" ? "你" : "AI 助手"}
                    </span>
                    <p>{message.content}</p>
                    {message.role === "assistant" ? (
                      <small>
                        {message.model} · 本次 {message.totalTokens} tokens
                      </small>
                    ) : null}
                  </div>
                </article>
              ))}
              {submitting ? (
                <article className="ai-chat-row ai-chat-assistant">
                  <span className="ai-message-avatar" aria-hidden="true">
                    <Sparkle size={14} />
                  </span>
                  <div
                    className="ai-chat-bubble ai-chat-thinking"
                    aria-label="AI 正在思考"
                  >
                    <i />
                    <i />
                    <i />
                  </div>
                </article>
              ) : null}
            </section>
          ) : null}
          {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
          <div ref={conversationEndRef} />
        </div>
        {canUseAi ? <form className="ai-composer" onSubmit={submit}>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                !event.shiftKey &&
                !event.nativeEvent.isComposing
              ) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="输入你的问题…"
            rows={4}
            aria-label="输入 AI 问题"
          />
          <div>
            <small>
              Enter 发送，Shift + Enter 换行；关闭窗口后清空本次对话
            </small>
            <button
              type="submit"
              className="primary-button compact"
              disabled={submitting || !status?.configured}
            >
              {submitting ? "思考中…" : "发送"}
            </button>
          </div>
        </form> : null}
      </aside>
    </div>
  );
}
