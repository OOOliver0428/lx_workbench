"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { localDateInputValue } from "../date-utils";
import { InlineNotice } from "../components/ui";
import { TimeBlockPicker } from "../components/time-block-picker";

/**
 * /time-block-demo —— 时间块圈选录入 Demo
 *
 * 演示用「区间圈选」替代原「投入时长（小时）」数字输入：
 * 一次提交同时携带合计耗时（沿用 hours → minutes 逻辑）与具体区间（time_blocks）。
 * 本页不请求后端，提交后仅展示将发送的载荷。
 */
export default function TimeBlockDemoPage() {
  const [payload, setPayload] = useState("");
  const [notice, setNotice] = useState("");
  const [formKey, setFormKey] = useState(0);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const hours = Number(form.get("time_hours"));
    if (!hours) {
      setPayload("");
      setNotice("");
      window.alert("请先在时间轴上圈选至少一个 0.5h 时间块。");
      return;
    }
    // 与 records-view.tsx 现有提交逻辑一致：minutes = hours * 60
    const body = {
      work_date: String(form.get("work_date")),
      content: String(form.get("content")),
      minutes: Math.round(hours * 60),
      time_blocks: JSON.parse(String(form.get("time_blocks") ?? "[]")),
    };
    setPayload(JSON.stringify(body, null, 2));
    setNotice("已生成提交载荷（Demo 未请求后端）。");
  }

  return (
    <div className="demo-page">
      <header>
        <p className="eyebrow">WORK LOG · DEMO</p>
        <h1>时间块圈选 · 耗时录入</h1>
        <p>
          在时间轴上按住并拖动即可圈选工作时间，最小粒度 0.5h；支持多段区间、
          拖动平移、两端改长、相邻自动合并。合计耗时与具体区间随表单一起提交。
        </p>
      </header>

      <section className="demo-panel">
        <h2>记录工作（表单集成示意）</h2>
        <p className="demo-panel-desc">
          仅将原「投入时长（小时）」数字输入替换为时间块圈选，其余字段与提交逻辑保持不变。
        </p>
        <form key={formKey} onSubmit={submit}>
          <div className="form-grid">
            <label className="field">
              <span>工作日期 *</span>
              <input
                name="work_date"
                type="date"
                defaultValue={localDateInputValue()}
                required
              />
            </label>
            <label className="field">
              <span>工作内容 *</span>
              <input
                name="content"
                required
                placeholder="例如：完成方案评审并修订总体架构图"
              />
            </label>
            <div className="field field-span-two">
              <span>投入时间（圈选时间块）*</span>
              <div className="tbp-scroll">
                <TimeBlockPicker
                  name="time"
                  onChange={() => {
                    setNotice("");
                  }}
                />
              </div>
            </div>
          </div>
          {notice ? <InlineNotice tone="success">{notice}</InlineNotice> : null}
          <footer className="modal-actions">
            <button
              type="button"
              className="secondary-button"
              onClick={() => {
                setFormKey((key) => key + 1);
                setPayload("");
                setNotice("");
              }}
            >
              重置
            </button>
            <button className="primary-button">保存记录</button>
          </footer>
        </form>
        {payload ? (
          <pre className="demo-payload" aria-label="提交载荷预览">
            {payload}
          </pre>
        ) : null}
      </section>

      <section className="demo-panel">
        <h2>交互说明</h2>
        <p className="demo-panel-desc">
          桌面端按住即拖；触屏需长按约 0.26s 激活拖动，避免与页面滚动冲突。
        </p>
        <ul style={{ color: "var(--ink-soft)", fontSize: 13, lineHeight: 2, margin: 0, paddingLeft: 18 }}>
          <li>空白处按住拖动：新建时间块（最小 0.5h，吸附半小时刻度）。</li>
          <li>拖动块体：整体平移；拖动块左右边缘：调整起止时间。</li>
          <li>多段区间重叠或首尾相接时，松手后自动合并为一个块。</li>
          <li>下方标签可单独删除某一段；「清空」移除全部时间块。</li>
          <li>
            隐藏字段 <code>time_hours</code>（合计小时）与 <code>time_blocks</code>
            （区间 JSON）随 FormData 提交，原 <code>minutes = hours × 60</code> 逻辑无需改动。
          </li>
        </ul>
      </section>

      <section className="demo-panel">
        <h2>数据库表拓展建议</h2>
        <p className="demo-panel-desc">
          新增子表保存区间明细；<code>work_records.minutes</code> 保留为冗余合计
          （等于各块时长之和），现有统计、校验（30 分钟粒度）与周报归集逻辑不受影响。
        </p>
        <pre className="demo-sql">{`-- 新增：工作记录时间块明细（一条记录 0..n 段区间）
CREATE TABLE work_record_time_blocks (
  id            VARCHAR(36) PRIMARY KEY,
  record_id     VARCHAR(36) NOT NULL
                REFERENCES work_records(id) ON DELETE CASCADE,
  start_minute  INTEGER NOT NULL,  -- 当天 00:00 起算，含
  end_minute    INTEGER NOT NULL,  -- 当天 00:00 起算，不含
  CONSTRAINT ck_wrtb_range
    CHECK (start_minute >= 0 AND end_minute <= 1440
           AND end_minute > start_minute),
  CONSTRAINT ck_wrtb_slot
    CHECK (start_minute % 30 = 0 AND end_minute % 30 = 0)
);
CREATE INDEX ix_wrtb_record ON work_record_time_blocks (record_id);

-- work_records 无需改列：minutes 仍存合计分钟数，
-- 由后端在写入时按 SUM(end_minute - start_minute) 计算并校验一致性。`}</pre>
      </section>
    </div>
  );
}
