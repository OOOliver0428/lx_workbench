"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import type { TimeBlock } from "../types";

/**
 * TimeBlockPicker —— 时间块圈选组件
 *
 * 交互：在时间轴上「按住并拖动」圈选 0.5h 粒度的时间块；
 * 支持多段区间、块体拖动平移、两端拖拽改长、相邻/重叠自动合并。
 * 触屏下需长按（约 260ms）激活拖动，避免与页面滚动手势冲突。
 *
 * 表单集成：渲染两个隐藏字段，可直接被 FormData 采集 ——
 *   ${name}_hours  → 合计小时数（沿用现有提交逻辑：minutes = hours * 60）
 *   ${name}_blocks → JSON 字符串 [{start, end}]，单位为当天 00:00 起的分钟数
 */

export type { TimeBlock };

const DAY_MINUTES = 24 * 60;
const SLOT_MINUTES = 30;
const LONG_PRESS_MS = 260;
const CANCEL_MOVE_PX = 10;
const EDGE_PX = 7;

type DragMode = "create" | "move" | "resize-start" | "resize-end";

interface DragState {
  pointerId: number;
  mode: DragMode;
  /** move/resize 目标块在 blocks 中的下标；create 模式下为 -1 */
  index: number;
  /** move 模式：按下点相对块起始的分钟偏移 */
  grabOffset: number;
  /** create 模式：锚定端分钟 */
  anchor: number;
  /** 触屏长按激活标记 */
  activated: boolean;
  startClientX: number;
  longPressTimer: number | null;
}

function clampMinute(value: number, rangeStart: number, rangeEnd: number) {
  return Math.min(rangeEnd, Math.max(rangeStart, value));
}

function snap(minute: number) {
  return Math.round(minute / SLOT_MINUTES) * SLOT_MINUTES;
}

export function formatMinute(minute: number) {
  const h = Math.floor(minute / 60);
  const m = minute % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function normalize(blocks: TimeBlock[], rangeStart: number, rangeEnd: number) {
  const sorted = blocks
    .map((block) => ({
      start: clampMinute(snap(block.start), rangeStart, rangeEnd),
      end: clampMinute(snap(block.end), rangeStart, rangeEnd),
    }))
    .filter((block) => block.end - block.start >= SLOT_MINUTES)
    .sort((a, b) => a.start - b.start);
  const merged: TimeBlock[] = [];
  for (const block of sorted) {
    const last = merged[merged.length - 1];
    if (last && block.start <= last.end) {
      last.end = Math.max(last.end, block.end);
    } else {
      merged.push({ ...block });
    }
  }
  return merged;
}

export function TimeBlockPicker({
  name = "time",
  defaultBlocks = [],
  rangeStart = 0,
  rangeEnd = DAY_MINUTES,
  onChange,
}: {
  /** 隐藏字段名前缀：生成 `${name}_hours` / `${name}_blocks` */
  name?: string;
  defaultBlocks?: TimeBlock[];
  /** 可选范围（分钟，当天 00:00 起算），默认全天 */
  rangeStart?: number;
  rangeEnd?: number;
  onChange?: (blocks: TimeBlock[], totalMinutes: number) => void;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragState | null>(null);
  const [blocks, setBlocks] = useState<TimeBlock[]>(() =>
    normalize(defaultBlocks, rangeStart, rangeEnd),
  );
  const [draft, setDraft] = useState<TimeBlock | null>(null);
  const [dragging, setDragging] = useState(false);

  const slotCount = (rangeEnd - rangeStart) / SLOT_MINUTES;
  const totalMinutes = useMemo(
    () => blocks.reduce((sum, block) => sum + (block.end - block.start), 0),
    [blocks],
  );

  const commit = useCallback(
    (next: TimeBlock[]) => {
      const merged = normalize(next, rangeStart, rangeEnd);
      setBlocks(merged);
      onChange?.(
        merged,
        merged.reduce((sum, block) => sum + (block.end - block.start), 0),
      );
    },
    [onChange, rangeEnd, rangeStart],
  );

  /** 指针横坐标 → 所在槽位的起始分钟（相对 rangeStart 的偏移换算） */
  const minuteAt = useCallback(
    (clientX: number) => {
      const track = trackRef.current;
      if (!track) return rangeStart;
      const rect = track.getBoundingClientRect();
      const ratio = (clientX - rect.left) / rect.width;
      const raw = rangeStart + ratio * (rangeEnd - rangeStart);
      return clampMinute(snap(raw), rangeStart, rangeEnd);
    },
    [rangeEnd, rangeStart],
  );

  /** 命中检测：返回块下标与命中部位 */
  const hitTest = useCallback(
    (clientX: number): { index: number; edge: "start" | "end" | "body" } | null => {
      const track = trackRef.current;
      if (!track) return null;
      const rect = track.getBoundingClientRect();
      const span = rangeEnd - rangeStart;
      for (let i = blocks.length - 1; i >= 0; i -= 1) {
        const block = blocks[i];
        const left = rect.left + ((block.start - rangeStart) / span) * rect.width;
        const right = rect.left + ((block.end - rangeStart) / span) * rect.width;
        if (clientX >= left - 1 && clientX <= right + 1) {
          if (clientX <= left + EDGE_PX) return { index: i, edge: "start" };
          if (clientX >= right - EDGE_PX) return { index: i, edge: "end" };
          return { index: i, edge: "body" };
        }
      }
      return null;
    },
    [blocks, rangeEnd, rangeStart],
  );

  const applyDrag = useCallback(
    (clientX: number) => {
      const drag = dragRef.current;
      if (!drag || !drag.activated) return;
      const minute = minuteAt(clientX);
      if (drag.mode === "create") {
        const start = Math.min(drag.anchor, minute);
        let end = Math.max(drag.anchor, minute);
        // 拖到端点上时向拖动方向多算一个槽，保证最小 0.5h 且端点直觉一致
        if (minute > drag.anchor) end = clampMinute(minute + SLOT_MINUTES, rangeStart, rangeEnd);
        else if (minute < drag.anchor) {
          end = clampMinute(drag.anchor + SLOT_MINUTES, rangeStart, rangeEnd);
        }
        setDraft({ start, end: Math.max(end, start + SLOT_MINUTES) });
        return;
      }
      setBlocks((current) => {
        const next = current.map((block) => ({ ...block }));
        const block = next[drag.index];
        if (!block) return current;
        const length = block.end - block.start;
        if (drag.mode === "move") {
          let start = snap(minute - drag.grabOffset);
          start = clampMinute(start, rangeStart, rangeEnd - length);
          block.start = start;
          block.end = start + length;
        } else if (drag.mode === "resize-start") {
          block.start = clampMinute(
            Math.min(minute, block.end - SLOT_MINUTES),
            rangeStart,
            rangeEnd,
          );
        } else {
          block.end = clampMinute(
            Math.max(minute, block.start + SLOT_MINUTES),
            rangeStart,
            rangeEnd,
          );
        }
        return next;
      });
    },
    [minuteAt, rangeEnd, rangeStart],
  );

  const finishDrag = useCallback(() => {
    const drag = dragRef.current;
    if (!drag) return;
    if (drag.longPressTimer !== null) window.clearTimeout(drag.longPressTimer);
    dragRef.current = null;
    setDragging(false);
    if (draft) {
      setDraft(null);
      commit([...blocks, draft]);
    } else if (drag.activated && drag.mode !== "create") {
      commit(blocks);
    }
  }, [blocks, commit, draft]);

  function onPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (dragRef.current) return;
    const hit = hitTest(event.clientX);
    const isTouch = event.pointerType === "touch";
    const drag: DragState = {
      pointerId: event.pointerId,
      mode: "create",
      index: -1,
      grabOffset: 0,
      anchor: 0,
      activated: !isTouch,
      startClientX: event.clientX,
      longPressTimer: null,
    };
    if (hit) {
      const block = blocks[hit.index];
      drag.index = hit.index;
      drag.mode =
        hit.edge === "start"
          ? "resize-start"
          : hit.edge === "end"
            ? "resize-end"
            : "move";
      if (drag.mode === "move") {
        drag.grabOffset = minuteAt(event.clientX) - block.start;
      }
    } else {
      drag.anchor = minuteAt(event.clientX);
      if (!isTouch) {
        setDraft({ start: drag.anchor, end: drag.anchor + SLOT_MINUTES });
      }
    }
    dragRef.current = drag;
    if (isTouch) {
      // 触屏：长按激活，激活前允许页面滚动；一旦激活即接管手势
      drag.longPressTimer = window.setTimeout(() => {
        const current = dragRef.current;
        if (!current) return;
        current.activated = true;
        setDragging(true);
        trackRef.current?.setPointerCapture(current.pointerId);
        if (current.mode === "create") {
          setDraft({ start: current.anchor, end: current.anchor + SLOT_MINUTES });
        }
      }, LONG_PRESS_MS);
    } else {
      setDragging(true);
      trackRef.current?.setPointerCapture(event.pointerId);
    }
  }

  function onPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (!drag.activated) {
      // 长按计时内明显移动 → 判定为滚动，放弃本次拖动
      if (Math.abs(event.clientX - drag.startClientX) > CANCEL_MOVE_PX) {
        if (drag.longPressTimer !== null) window.clearTimeout(drag.longPressTimer);
        dragRef.current = null;
      }
      return;
    }
    applyDrag(event.clientX);
  }

  function onPointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    finishDrag();
  }

  function removeBlock(index: number) {
    commit(blocks.filter((_, i) => i !== index));
  }

  const span = rangeEnd - rangeStart;
  const toPercent = (minute: number) =>
    `${((minute - rangeStart) / span) * 100}%`;

  // 刻度：每小时一条线，每 2 小时一个文字标签
  const hourTicks = useMemo(() => {
    const ticks: number[] = [];
    for (let m = rangeStart; m <= rangeEnd; m += 60) ticks.push(m);
    return ticks;
  }, [rangeEnd, rangeStart]);

  return (
    <div className={`time-block-picker${dragging ? " is-dragging" : ""}`}>
      <div className="tbp-ruler" aria-hidden="true">
        {hourTicks.map((tick) =>
          tick < rangeEnd ? (
            <span
              key={tick}
              className={tick % 120 === 0 ? "tbp-tick-major" : "tbp-tick-minor"}
              style={{ left: toPercent(tick) }}
            >
              {tick % 120 === 0 ? `${Math.floor(tick / 60)}:00` : ""}
            </span>
          ) : null,
        )}
        <span className="tbp-tick-major" style={{ left: "100%" }}>
          {Math.floor(rangeEnd / 60)}:00
        </span>
      </div>
      <div
        ref={trackRef}
        className="tbp-track"
        role="group"
        aria-label="按住拖动圈选工作时间块，最小 0.5 小时"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {Array.from({ length: slotCount }, (_, i) => (
          <i
            key={i}
            className={i % 2 === 0 ? "tbp-slot tbp-slot-hour" : "tbp-slot"}
            style={{ left: toPercent(rangeStart + i * SLOT_MINUTES) }}
            aria-hidden="true"
          />
        ))}
        {blocks.map((block) => (
          <div
            key={`${block.start}-${block.end}`}
            className="tbp-block"
            style={{
              left: toPercent(block.start),
              width: `calc(${toPercent(block.end)} - ${toPercent(block.start)})`,
            }}
          >
            <span className="tbp-block-label">
              {formatMinute(block.start)}–{formatMinute(block.end)}
            </span>
            <b className="tbp-edge tbp-edge-start" aria-hidden="true" />
            <b className="tbp-edge tbp-edge-end" aria-hidden="true" />
          </div>
        ))}
        {draft ? (
          <div
            className="tbp-block tbp-block-draft"
            style={{
              left: toPercent(draft.start),
              width: `calc(${toPercent(draft.end)} - ${toPercent(draft.start)})`,
            }}
          >
            <span className="tbp-block-label">
              {formatMinute(draft.start)}–{formatMinute(draft.end)}
            </span>
          </div>
        ) : null}
        {!blocks.length && !draft ? (
          <em className="tbp-hint">按住并拖动，圈选工作时间段（最小 0.5h）</em>
        ) : null}
      </div>
      <div className="tbp-summary">
        <span className={`tbp-total${totalMinutes ? "" : " is-empty"}`}>
          合计 {totalMinutes ? (totalMinutes / 60).toFixed(1).replace(/\.0$/, "") : "0"}h
        </span>
        {blocks.map((block, index) => (
          <span className="tbp-chip" key={`${block.start}-${block.end}`}>
            {formatMinute(block.start)}–{formatMinute(block.end)}
            <button
              type="button"
              aria-label={`删除 ${formatMinute(block.start)} 到 ${formatMinute(block.end)} 的时间块`}
              onClick={() => removeBlock(index)}
            >
              ×
            </button>
          </span>
        ))}
        {blocks.length ? (
          <button
            type="button"
            className="tbp-clear"
            onClick={() => commit([])}
          >
            清空
          </button>
        ) : null}
      </div>
      <input type="hidden" name={`${name}_hours`} value={(totalMinutes / 60).toString()} />
      <input
        type="hidden"
        name={`${name}_blocks`}
        value={JSON.stringify(blocks)}
      />
    </div>
  );
}
