"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiClientError } from "../api";
import type { ChangelogCategory, ChangelogEntry } from "../types";
import { EmptyState, InlineNotice, Modal } from "./ui";

const CATEGORY_LABELS: Record<ChangelogCategory, string> = {
  feature: "新功能",
  improvement: "优化",
  fix: "修复",
  removal: "下线",
  release: "版本更新",
};

const CATEGORY_OPTIONS: ChangelogCategory[] = [
  "feature",
  "improvement",
  "fix",
  "removal",
  "release",
];

function shanghaiDayKey(iso: string) {
  const date = new Date(
    new Date(iso).toLocaleString("en-US", { timeZone: "Asia/Shanghai" }),
  );
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function shanghaiDayLabel(dayKey: string) {
  const date = new Date(`${dayKey}T12:00:00+08:00`);
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
  }).format(date);
}

function shanghaiTimeLabel(iso: string) {
  const date = new Date(
    new Date(iso).toLocaleString("en-US", { timeZone: "Asia/Shanghai" }),
  );
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function toDatetimeLocalValue(iso: string) {
  const date = new Date(
    new Date(iso).toLocaleString("en-US", { timeZone: "Asia/Shanghai" }),
  );
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function nowDatetimeLocalValue() {
  return toDatetimeLocalValue(new Date().toISOString());
}

function groupByDay(entries: ChangelogEntry[]) {
  const groups = new Map<string, ChangelogEntry[]>();
  for (const entry of entries) {
    const key = shanghaiDayKey(entry.occurred_at);
    groups.set(key, [...(groups.get(key) ?? []), entry]);
  }
  return [...groups.entries()];
}

export function ChangelogView({ canManage }: { canManage: boolean }) {
  const [entries, setEntries] = useState<ChangelogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<ChangelogEntry | null>(null);
  const [deletingId, setDeletingId] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const rows = await api.changelog.list();
      setEntries(rows);
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "更新日志加载失败",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timeout = window.setTimeout(load, 0);
    return () => window.clearTimeout(timeout);
  }, [load]);

  const groups = useMemo(() => groupByDay(entries), [entries]);

  async function removeEntry(entry: ChangelogEntry) {
    if (!window.confirm(`确认删除更新日志「${entry.title}」？`)) return;
    setDeletingId(entry.id);
    setError("");
    try {
      await api.changelog.remove(entry.id, entry.revision);
      setNotice("已删除该条更新日志。");
      await load();
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "删除更新日志失败",
      );
    } finally {
      setDeletingId("");
    }
  }

  return (
    <div className="view-shell changelog-page">
      <header className="view-header">
        <div>
          <p className="eyebrow">CHANGELOG</p>
          <h1>更新日志</h1>
          <p>最近发生了什么 — 新功能、调整、下线，都写在这里。</p>
        </div>
        {canManage ? (
          <button
            type="button"
            className="primary-button"
            onClick={() => setCreating(true)}
          >
            新建条目
          </button>
        ) : null}
      </header>

      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
      {notice ? <InlineNotice>{notice}</InlineNotice> : null}

      {loading ? (
        <section className="changelog-loading" aria-live="polite">
          正在读取更新日志…
        </section>
      ) : entries.length ? (
        <div className="changelog-timeline">
          {groups.map(([dayKey, dayEntries]) => (
            <section className="changelog-day" key={dayKey}>
              <h2>
                {shanghaiDayLabel(dayKey)}
              </h2>
              <div className="changelog-day-entries">
                {dayEntries.map((entry) => entry.category === "release" ? (
                  <article className="changelog-release" key={entry.id}>
                    <div className="changelog-release-divider" role="separator" aria-label={`版本更新 ${entry.title}`}>
                      <h3>{entry.title}</h3>
                    </div>
                    {canManage ? (
                      <div className="changelog-release-actions">
                        <button type="button" className="text-button" onClick={() => setEditing(entry)}>
                          编辑
                        </button>
                        <button type="button" className="text-button" disabled={deletingId === entry.id}
                          style={{ color: "var(--red)" }} onClick={() => removeEntry(entry)}>
                          {deletingId === entry.id ? "删除中…" : "删除"}
                        </button>
                      </div>
                    ) : null}
                  </article>
                ) : (
                  <article className="changelog-entry" key={entry.id}>
                    <div className="changelog-entry-meta">
                      <strong>{shanghaiTimeLabel(entry.occurred_at)}</strong>
                      <span className={`changelog-tag tag-${entry.category}`}>
                        <i aria-hidden="true" />
                        {CATEGORY_LABELS[entry.category] ?? entry.category}
                      </span>
                      {canManage ? (
                        <div className="changelog-entry-actions">
                          <button
                            type="button"
                            className="text-button"
                            onClick={() => setEditing(entry)}
                          >
                            编辑
                          </button>
                          <button
                            type="button"
                            className="text-button"
                            disabled={deletingId === entry.id}
                            style={{ color: "var(--red)" }}
                            onClick={() => removeEntry(entry)}
                          >
                            {deletingId === entry.id ? "删除中…" : "删除"}
                          </button>
                        </div>
                      ) : null}
                    </div>
                    <div className="changelog-entry-body">
                      <h3>{entry.title}</h3>
                      <p>{entry.body}</p>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <EmptyState
          title="暂无更新日志"
          description={
            canManage
              ? "点击右上角「新建条目」发布第一条产品更新。"
              : "产品更新发布后会显示在这里。"
          }
        />
      )}

      {creating ? (
        <ChangelogEntryModal
          onClose={() => setCreating(false)}
          onSaved={async (message) => {
            setCreating(false);
            setNotice(message);
            await load();
          }}
        />
      ) : null}
      {editing ? (
        <ChangelogEntryModal
          entry={editing}
          onClose={() => setEditing(null)}
          onSaved={async (message) => {
            setEditing(null);
            setNotice(message);
            await load();
          }}
        />
      ) : null}
    </div>
  );
}

function ChangelogEntryModal({
  entry,
  onClose,
  onSaved,
}: {
  entry?: ChangelogEntry;
  onClose: () => void;
  onSaved: (message: string) => void | Promise<void>;
}) {
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [category, setCategory] = useState<ChangelogCategory>(entry?.category ?? "improvement");
  const isRelease = category === "release";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    const form = new FormData(event.currentTarget);
    const occurredLocal = String(form.get("occurred_at") || "");
    const occurredAt = occurredLocal
      ? new Date(`${occurredLocal}:00+08:00`).toISOString()
      : (entry?.occurred_at ?? new Date().toISOString());
    const payload = {
      occurred_at: occurredAt,
      category,
      title: String(form.get(isRelease ? "version" : "title") || "").trim(),
      body: isRelease ? "" : String(form.get("body") || "").trim(),
    };
    try {
      if (entry) {
        await api.changelog.update(entry.id, {
          revision: entry.revision,
          ...payload,
        });
        await onSaved("更新日志已保存。");
      } else {
        await api.changelog.create(payload);
        await onSaved("更新日志已发布。");
      }
    } catch (caught) {
      setError(
        caught instanceof ApiClientError ? caught.message : "保存更新日志失败",
      );
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title={entry ? "编辑更新日志" : "新建更新日志"}
      eyebrow="CHANGELOG ENTRY"
      onClose={onClose}
      wide
    >
      <form className="modal-form" onSubmit={submit}>
        <div className="form-grid">
          {!isRelease ? (
          <label className="field">
            <span>发生时间 *</span>
            <input
              name="occurred_at"
              type="datetime-local"
              required
              defaultValue={
                entry ? toDatetimeLocalValue(entry.occurred_at) : nowDatetimeLocalValue()
              }
            />
          </label>
          ) : null}
          <label className="field">
            <span>类型 *</span>
            <select
              name="category"
              required
              value={category}
              onChange={(event) => setCategory(event.target.value as ChangelogCategory)}
            >
              {CATEGORY_OPTIONS.map((category) => (
                <option key={category} value={category}>
                  {CATEGORY_LABELS[category]}
                </option>
              ))}
            </select>
          </label>
          {isRelease ? (
            <label className="field field-span-two">
              <span>升级到的版本号 *</span>
              <input name="version" required maxLength={80}
                defaultValue={entry?.category === "release" ? entry.title : ""}
                placeholder="例如 0.3.1" autoFocus />
              <small className="field-hint">保存后以居中的版本分割线展示。</small>
            </label>
          ) : (
          <>
          <label className="field field-span-two">
            <span>标题 *</span>
            <input
              name="title"
              required
              maxLength={200}
              defaultValue={entry?.category === "release" ? "" : entry?.title ?? ""}
              placeholder="例如 日报、周报和月报，重点更清楚了"
              autoFocus
            />
          </label>
          <label className="field field-span-two">
            <span>说明 *</span>
            <textarea
              name="body"
              required
              rows={5}
              maxLength={20000}
              defaultValue={entry?.body ?? ""}
              placeholder="用一两段话说明这次变更对使用者的影响"
            />
          </label>
          </>
          )}
        </div>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" disabled={submitting}>
            {submitting ? "正在保存…" : entry ? "保存修改" : "发布"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}
