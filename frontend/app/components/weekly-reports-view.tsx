"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiClientError } from "../api";
import type { TeamWeeklySummary, WeeklyReport } from "../types";
import { EmptyState, InlineNotice } from "./ui";

type WeeklyReportTab = "mine" | "team";

export function WeeklyReportsView({
  canManage,
  canViewTeamReports,
}: {
  canManage: boolean;
  canViewTeamReports: boolean;
}) {
  const [tab, setTab] = useState<WeeklyReportTab>("mine");
  const [ownReports, setOwnReports] = useState<WeeklyReport[]>([]);
  const [teamReports, setTeamReports] = useState<TeamWeeklySummary[]>([]);
  const [selectedOwnId, setSelectedOwnId] = useState("");
  const [selectedTeamId, setSelectedTeamId] = useState("");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try {
      const [own, team] = await Promise.all([
        api.weeklyReports.list(),
        canViewTeamReports
          ? api.weeklyReports.teamSummaries()
          : Promise.resolve([]),
      ]);
      setOwnReports(own);
      setTeamReports(team);
      setSelectedOwnId((current) =>
        own.some((report) => report.id === current)
          ? current
          : (own[0]?.id ?? ""),
      );
      setSelectedTeamId((current) =>
        team.some((report) => report.id === current)
          ? current
          : (team[0]?.id ?? ""),
      );
      setError("");
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "周报数据加载失败",
      );
    }
  }, [canViewTeamReports]);

  useEffect(() => {
    const timeout = window.setTimeout(load, 0);
    return () => window.clearTimeout(timeout);
  }, [load]);

  const selectedOwnReport = useMemo(
    () => ownReports.find((report) => report.id === selectedOwnId) ?? null,
    [ownReports, selectedOwnId],
  );
  const selectedTeamReport = useMemo(
    () =>
      teamReports.find((report) => report.id === selectedTeamId) ?? null,
    [selectedTeamId, teamReports],
  );
  const draftContent = selectedOwnReport
    ? (drafts[selectedOwnReport.id] ?? selectedOwnReport.content)
    : "";

  function replaceOwnReport(report: WeeklyReport) {
    setOwnReports((current) => {
      const exists = current.some((item) => item.id === report.id);
      const next = exists
        ? current.map((item) => (item.id === report.id ? report : item))
        : [report, ...current];
      return next.sort((left, right) =>
        right.week_start.localeCompare(left.week_start),
      );
    });
    setSelectedOwnId(report.id);
    setDrafts((current) => ({ ...current, [report.id]: report.content }));
  }

  async function generateCurrentReport() {
    const today = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Shanghai",
    }).format(new Date());
    const current = ownReports.find(
      (report) => report.week_start <= today && report.week_end >= today,
    );
    if (
      current &&
      !window.confirm("重新生成会覆盖本周当前草稿，已提交版本仍会保留。是否继续？")
    ) {
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const generated = await api.weeklyReports.generateCurrent();
      replaceOwnReport(generated);
      setMessage("本周周报已通过 AI 生成并保存为草稿。");
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "AI 生成周报失败",
      );
    } finally {
      setBusy(false);
    }
  }

  async function saveDraft(report = selectedOwnReport) {
    if (!report || !draftContent.trim()) return null;
    const saved = await api.weeklyReports.saveDraft(
      report.id,
      report.revision,
      draftContent,
    );
    replaceOwnReport(saved);
    return saved;
  }

  async function handleSaveDraft() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const saved = await saveDraft();
      if (saved) setMessage("草稿已保存。");
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "保存草稿失败",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmit() {
    if (!selectedOwnReport || !draftContent.trim()) return;
    const overwriteConfirmed = Boolean(selectedOwnReport.submitted_at);
    if (
      overwriteConfirmed &&
      !window.confirm("该周已有已提交版本，本次提交将更新正式版本。是否继续？")
    ) {
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      let report = selectedOwnReport;
      if (draftContent !== report.content) {
        const saved = await saveDraft(report);
        if (!saved) return;
        report = saved;
      }
      const submitted = await api.weeklyReports.submit(
        report.id,
        report.revision,
        overwriteConfirmed,
      );
      replaceOwnReport(submitted);
      setMessage(`已提交正式版本 V${submitted.submission_version}。`);
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "提交周报失败",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="view-shell">
      <header className="view-header">
        <div>
          <p className="eyebrow">WEEKLY REPORTS</p>
          <h1>周报</h1>
          <p>按周目维护自己的周报；个人草稿和正式版本只对本人可见。</p>
        </div>
        {tab === "mine" && canManage ? (
          <button
            className="primary-button"
            disabled={busy}
            onClick={generateCurrentReport}
          >
            AI 生成本周周报
          </button>
        ) : null}
      </header>

      <div className="section-tabs" aria-label="周报类型">
        <button
          className={tab === "mine" ? "active" : ""}
          onClick={() => setTab("mine")}
        >
          我的周报 <span>{ownReports.length}</span>
        </button>
        {canViewTeamReports ? (
          <button
            className={tab === "team" ? "active" : ""}
            onClick={() => setTab("team")}
          >
            团队周报 <span>{teamReports.length}</span>
          </button>
        ) : null}
      </div>

      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
      {message ? <InlineNotice tone="success">{message}</InlineNotice> : null}
      {tab === "mine" && !canManage ? (
        <InlineNotice>当前账号只有查看权限，编辑、生成和提交操作已隐藏。</InlineNotice>
      ) : null}

      {tab === "mine" ? (
        <PersonalReportPanel
          reports={ownReports}
          selectedReport={selectedOwnReport}
          selectedId={selectedOwnId}
          draftContent={draftContent}
          canManage={canManage}
          busy={busy}
          onSelect={(value) => {
            setSelectedOwnId(value);
            setMessage("");
            setError("");
          }}
          onDraftChange={(value) => {
            if (!selectedOwnReport) return;
            setDrafts((current) => ({
              ...current,
              [selectedOwnReport.id]: value,
            }));
          }}
          onSave={handleSaveDraft}
          onSubmit={handleSubmit}
        />
      ) : (
        <TeamReportPanel
          reports={teamReports}
          selectedReport={selectedTeamReport}
          selectedId={selectedTeamId}
          onSelect={setSelectedTeamId}
        />
      )}
    </div>
  );
}

function PersonalReportPanel({
  reports,
  selectedReport,
  selectedId,
  draftContent,
  canManage,
  busy,
  onSelect,
  onDraftChange,
  onSave,
  onSubmit,
}: {
  reports: WeeklyReport[];
  selectedReport: WeeklyReport | null;
  selectedId: string;
  draftContent: string;
  canManage: boolean;
  busy: boolean;
  onSelect: (value: string) => void;
  onDraftChange: (value: string) => void;
  onSave: () => void;
  onSubmit: () => void;
}) {
  if (!reports.length) {
    return (
      <EmptyState
        title="还没有周报"
        description={
          canManage
            ? "点击“AI 生成本周周报”，系统会根据你本周的工作记录生成草稿。"
            : "获得“维护个人周报”权限后可生成并维护周报。"
        }
      />
    );
  }

  return (
    <section className="report-section report-workspace">
      <div className="report-section-heading">
        <div>
          <p className="eyebrow">MY REPORTS</p>
          <h2>我的周报</h2>
        </div>
        <label className="report-week-picker">
          <span>选择周目</span>
          <select
            aria-label="选择个人周报周目"
            value={selectedId}
            onChange={(event) => onSelect(event.target.value)}
          >
            {reports.map((report) => (
              <option key={report.id} value={report.id}>
                {formatWeek(report.week_start, report.week_end)} ·{" "}
                {report.submitted_at
                  ? `已提交 V${report.submission_version}`
                  : "草稿"}
              </option>
            ))}
          </select>
        </label>
      </div>
      {selectedReport ? (
        <>
          <div className="report-status-line">
            {selectedReport.submitted_at && !selectedReport.department_snapshot_known && !selectedReport.department_id ? <span>历史部门归属未知</span> : null}
            <span>
              {selectedReport.submitted_at
                ? `已提交 V${selectedReport.submission_version}`
                : "尚未提交"}
            </span>
            <span>
              {selectedReport.has_unsubmitted_changes
                ? "有未提交修改"
                : "草稿与正式版本一致"}
            </span>
          </div>
          <textarea
            className="weekly-report-editor report-page-editor"
            aria-label="周报草稿内容"
            value={draftContent}
            readOnly={!canManage}
            onChange={(event) => onDraftChange(event.target.value)}
          />
          {canManage ? (
            <div className="weekly-report-actions">
              <button
                className="secondary-button"
                disabled={
                  busy ||
                  !draftContent.trim() ||
                  draftContent === selectedReport.content
                }
                onClick={onSave}
              >
                保存草稿
              </button>
              <button
                className="primary-button"
                disabled={busy || !draftContent.trim()}
                onClick={onSubmit}
              >
                {selectedReport.submitted_at ? "更新正式版本" : "提交周报"}
              </button>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function TeamReportPanel({
  reports,
  selectedReport,
  selectedId,
  onSelect,
}: {
  reports: TeamWeeklySummary[];
  selectedReport: TeamWeeklySummary | null;
  selectedId: string;
  onSelect: (value: string) => void;
}) {
  if (!reports.length) {
    return (
      <EmptyState
        title="还没有团队周报"
        description="在作战台生成团队周报后，可在这里按周目查看历史版本。"
      />
    );
  }

  return (
    <section className="report-section report-workspace">
      <div className="report-section-heading">
        <div>
          <p className="eyebrow">TEAM REPORTS</p>
          <h2>{selectedReport?.scope_type === "legacy" ? "历史团队汇总（旧版范围）" : "往期团队周报"}</h2>
        </div>
        <label className="report-week-picker">
          <span>选择周目</span>
          <select
            aria-label="选择团队周报周目"
            value={selectedId}
            onChange={(event) => onSelect(event.target.value)}
          >
            {reports.map((report) => (
              <option key={report.id} value={report.id}>
                {report.scope_type === "legacy" ? "历史团队汇总 · " : ""}{formatWeek(report.week_start, report.week_end)} ·{" "}
                {formatDateTime(report.created_at)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {selectedReport ? (
        <>
          <div className="report-status-line">
            <span>
              汇总 {selectedReport.submitted_count}/
              {selectedReport.expected_count_known === false ? "未知（历史成员名单缺失）" : selectedReport.expected_count} 份个人周报
            </span>
            <span>{selectedReport.expected_count_known === false ? "按已知提交生成" : selectedReport.forced ? "缺交强制生成" : "完整生成"}</span>
          </div>
          <pre className="team-report-content">{selectedReport.content}</pre>
        </>
      ) : null}
    </section>
  );
}

function formatWeek(start: string, end: string) {
  return `${start} 至 ${end}`;
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}
