"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiClientError } from "../api";
import type {
  UserRole,
  WeeklyReport,
  WeeklyReportInboxItem,
} from "../types";
import { EmptyState, InlineNotice } from "./ui";

export function WeeklyReportsView({ role }: { role: UserRole }) {
  const [ownReports, setOwnReports] = useState<WeeklyReport[]>([]);
  const [inbox, setInbox] = useState<WeeklyReportInboxItem[]>([]);
  const [error, setError] = useState("");
  const canReadInbox =
    role === "team_leader" ||
    role === "system_admin" ||
    role === "super_admin";

  const load = useCallback(async () => {
    try {
      const [own, received] = await Promise.all([
        api.weeklyReports.list(),
        canReadInbox ? api.weeklyReports.inbox() : Promise.resolve([]),
      ]);
      setOwnReports(own);
      setInbox(received);
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "周报数据加载失败",
      );
    }
  }, [canReadInbox]);

  useEffect(() => {
    const timeout = window.setTimeout(load, 0);
    return () => window.clearTimeout(timeout);
  }, [load]);

  return (
    <div className="view-shell">
      <header className="view-header">
        <div>
          <p className="eyebrow">WEEKLY REPORTS</p>
          <h1>周报</h1>
          <p>个人周报通过 AI 助手生成、编辑并提交；此处保留提交状态与历史记录。</p>
        </div>
      </header>
      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}

      <section className="report-section">
        <div className="report-section-heading">
          <div>
            <p className="eyebrow">MY REPORTS</p>
            <h2>我的周报</h2>
          </div>
          <span>{ownReports.length} 周</span>
        </div>
        {ownReports.length ? (
          <div className="weekly-report-list">
            {ownReports.map((report) => (
              <details key={report.id}>
                <summary>
                  <span>
                    <strong>
                      {report.week_start} 至 {report.week_end}
                    </strong>
                    <small>
                      {report.submitted_at
                        ? `已提交 V${report.submission_version}`
                        : "仅草稿"}
                    </small>
                  </span>
                  <i>{report.has_unsubmitted_changes ? "有未提交修改" : "已同步"}</i>
                </summary>
                <pre>{report.content}</pre>
              </details>
            ))}
          </div>
        ) : (
          <EmptyState
            title="还没有周报"
            description="打开左下角 AI 助手，点击“生成本周周报”开始。"
          />
        )}
      </section>

      {canReadInbox ? (
        <section className="report-section">
          <div className="report-section-heading">
            <div>
              <p className="eyebrow">LEADER INBOX</p>
              <h2>直属成员已提交周报</h2>
            </div>
            <span>{inbox.length} 份</span>
          </div>
          {inbox.length ? (
            <div className="weekly-report-list leader-inbox">
              {inbox.map((report) => (
                <details key={report.id}>
                  <summary>
                    <span>
                      <strong>{report.author_display_name}</strong>
                      <small>
                        {report.week_start} 至 {report.week_end}
                      </small>
                    </span>
                    <i>已提交 V{report.submission_version}</i>
                  </summary>
                  <pre>{report.content}</pre>
                </details>
              ))}
            </div>
          ) : (
            <EmptyState
              title="暂无已提交周报"
              description="这里只显示直属成员已经正式提交的版本，不显示草稿。"
            />
          )}
        </section>
      ) : null}
    </div>
  );
}
