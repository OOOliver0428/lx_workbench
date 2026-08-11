"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { CSSProperties } from "react";
import type { Task, TaskStatus, UserCandidate } from "../types";
import { AvatarImage } from "./avatar";
import { ChevronLeft } from "./icons";
import { InlineNotice, Modal, StatusBadge } from "./ui";

export interface TaskGroup {
  key: string;
  kind: "project" | "work";
  id: string;
  name: string;
  tasks: Task[];
}

type SortKey = "priority" | "due" | "status";

const TERMINAL_STATUSES: ReadonlySet<TaskStatus> = new Set([
  "done",
  "cancelled",
]);

const STATUS_LABELS: Record<TaskStatus, string> = {
  todo: "待开始",
  in_progress: "处理中",
  blocked: "阻塞",
  done: "已完成",
  cancelled: "已取消",
};

const PRIORITY_LABELS: Record<Task["priority"], string> = {
  p0: "P0",
  p1: "P1",
  p2: "P2",
};

const PRIORITY_COLORS: Record<Task["priority"], string> = {
  p0: "#b44e43",
  p1: "#1677ff",
  p2: "#8ca1b2",
};

const PRIORITY_RANK: Record<Task["priority"], number> = { p0: 0, p1: 1, p2: 2 };

const STATUS_RANK: Record<TaskStatus, number> = {
  in_progress: 4,
  blocked: 3,
  todo: 2,
  done: 1,
  cancelled: 0,
};

const CARD_W = 200;
const CARD_H = 120;
const GAP_X = 44;
const GAP_Y = 80;
const PILE_W = 190;
const PILE_DX = 34;

function compareTasks(a: Task, b: Task, key: SortKey) {
  const order: SortKey[] =
    key === "priority"
      ? ["priority", "due", "status"]
      : key === "due"
        ? ["due", "priority", "status"]
        : ["status", "priority", "due"];
  for (const field of order) {
    let delta = 0;
    if (field === "priority") {
      delta = PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority];
    } else if (field === "status") {
      delta = STATUS_RANK[b.status] - STATUS_RANK[a.status];
    } else {
      const left = a.due_date ?? "9999-12-31";
      const right = b.due_date ?? "9999-12-31";
      delta = left < right ? -1 : left > right ? 1 : 0;
    }
    if (delta) return delta;
  }
  return 0;
}

function groupAccent(value: string) {
  const colors = [
    "#1677ff",
    "#6b5cff",
    "#16b987",
    "#e98a32",
    "#e94f9b",
    "#16a5d9",
    "#13a8a8",
  ];
  const hash = [...value].reduce(
    (sum, character) => sum + character.charCodeAt(0),
    0,
  );
  return colors[hash % colors.length];
}

function childrenOf(tasks: Task[], parentId: string) {
  return tasks.filter((task) => task.parent_id === parentId);
}

/* ================= 总览（分组单元） ================= */

export function TaskGroupOverview({
  groups,
  onOpenGroup,
}: {
  groups: TaskGroup[];
  onOpenGroup: (group: TaskGroup) => void;
}) {
  return (
    <div className="task-unit-grid">
      {groups.map((group) => (
        <TaskUnit
          key={group.key}
          group={group}
          onOpen={() => onOpenGroup(group)}
        />
      ))}
    </div>
  );
}

function TaskUnit({
  group,
  onOpen,
}: {
  group: TaskGroup;
  onOpen: () => void;
}) {
  const count = group.tasks.length;
  const childCount = group.tasks.filter((task) => task.parent_id).length;
  const variant = count === 1 ? "单卡" : count <= 5 ? "卡片堆" : "卡片箱";
  return (
    <div
      className="task-unit"
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
      aria-label={`${group.name}，${count} 个任务，点击进入`}
    >
      {count === 1 ? (
        <SoloVisual task={group.tasks[0]} />
      ) : count <= 5 ? (
        <StackVisual count={count} />
      ) : (
        <CrateVisual />
      )}
      <div className="task-unit-frost">
        <div className="tuf-top">
          <strong className="tuf-name">{group.name}</strong>
          <span className="tuf-tag">{variant}</span>
        </div>
        <div className="tuf-bottom">
          <span
            className="tuf-count"
            style={{ background: groupAccent(group.id) }}
          >
            +{count}
          </span>
          <span className="tuf-meta">
            {group.kind === "project" ? "项目" : "部门工作"} · {count} 个任务
            {childCount ? ` · 含 ${childCount} 个子任务` : ""}
          </span>
        </div>
      </div>
    </div>
  );
}

function SoloVisual({ task }: { task: Task }) {
  return (
    <div className="tu-stackwrap">
      <div className="tu-sh tu-front tu-solo">
        <span className="tu-solo-name">{task.title}</span>
        <span className="tu-solo-meta">
          {STATUS_LABELS[task.status]}
          {task.due_date ? ` · 截止 ${task.due_date.slice(5)}` : ""}
        </span>
      </div>
    </div>
  );
}

function StackVisual({ count }: { count: number }) {
  const offsets: Array<[number, number, number]> = [
    [4, 9, 8],
    [-5, -10, 6],
    [2, 1, 14],
  ];
  const ghosts = Math.min(count - 1, 3);
  return (
    <div className="tu-stackwrap">
      {Array.from({ length: ghosts }, (_, index) => ghosts - index).map(
        (layer) => {
          const [rotate, shiftX, shiftY] = offsets[layer - 1];
          return (
            <i
              key={layer}
              className="tu-sh tu-ghost"
              style={
                {
                  "--r": `${rotate}deg`,
                  "--x": `${shiftX}px`,
                  "--y": `${shiftY}px`,
                } as CSSProperties
              }
            />
          );
        },
      )}
      <div className="tu-sh tu-front">
        <span className="tu-redact">
          <i style={{ width: "92%" }} />
          <i style={{ width: "64%" }} />
        </span>
        <span className="tu-redact thin">
          <i style={{ width: "46%" }} />
        </span>
      </div>
    </div>
  );
}

function CrateVisual() {
  const sticks = [
    { left: 8, rotate: -8, height: 62 },
    { left: 56, rotate: -2, height: 72 },
    { left: 104, rotate: 4, height: 56 },
    { left: 148, rotate: 9, height: 66 },
  ];
  return (
    <div className="tu-crate">
      {sticks.map((stick, index) => (
        <i
          key={index}
          className="tu-stick"
          style={
            {
              left: stick.left,
              height: stick.height,
              transitionDelay: `${index * 45}ms`,
              "--r": `${stick.rotate}deg`,
            } as CSSProperties
          }
        >
          <span className="tu-stick-bars">
            <i style={{ width: "82%" }} />
            <i style={{ width: "56%" }} />
            <i style={{ width: "68%" }} />
          </span>
        </i>
      ))}
      <div className="tu-crate-box">
        <i className="tu-crate-lid" />
      </div>
    </div>
  );
}

/* ================= 分组详情（平铺 / 堆叠） ================= */

export function TaskGroupDetail({
  group,
  userNames,
  onBack,
  onOpenTask,
}: {
  group: TaskGroup;
  userNames: Map<string, string>;
  onBack: () => void;
  onOpenTask: (task: Task) => void;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("priority");
  const canPile = group.tasks.length > 9;
  const [spread, setSpread] = useState(!canPile);
  const [hasSpread, setHasSpread] = useState(false);
  const flatCardElements = useRef(new Map<string, HTMLDivElement>());
  const pileCardElements = useRef(new Map<string, HTMLDivElement>());
  const pileCenters = useRef(new Map<string, { x: number; y: number }>());
  const pendingFlip = useRef<Map<string, { x: number; y: number }> | null>(
    null,
  );
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    text: string;
  } | null>(null);
  const collapseTimer = useRef(0);

  const registerFlatCard = useCallback(
    (id: string, element: HTMLDivElement | null) => {
      if (element) flatCardElements.current.set(id, element);
      else flatCardElements.current.delete(id);
    },
    [],
  );

  const registerPileCard = useCallback(
    (id: string, element: HTMLDivElement | null) => {
      if (element) pileCardElements.current.set(id, element);
      else pileCardElements.current.delete(id);
    },
    [],
  );

  const sortedTasks = useMemo(() => {
    const ids = new Set(group.tasks.map((task) => task.id));
    const roots = group.tasks
      .filter((task) => !task.parent_id || !ids.has(task.parent_id))
      .sort((a, b) => compareTasks(a, b, sortKey));
    const placed = new Set<string>();
    const ordered: Task[] = [];
    for (const root of roots) {
      placed.add(root.id);
      ordered.push(root);
      for (const child of childrenOf(group.tasks, root.id).sort((a, b) =>
        compareTasks(a, b, sortKey),
      )) {
        if (!placed.has(child.id)) {
          placed.add(child.id);
          ordered.push(child);
        }
      }
    }
    for (const task of group.tasks) {
      if (!placed.has(task.id)) ordered.push(task);
    }
    return ordered;
  }, [group.tasks, sortKey]);

  const layout = useMemo(() => {
    const ids = new Set(group.tasks.map((task) => task.id));
    const roots = sortedTasks.filter(
      (task) => !task.parent_id || !ids.has(task.parent_id),
    );
    const positions = new Map<string, { x: number; y: number }>();
    let x = 0;
    let hasKids = false;
    for (const root of roots) {
      const kids = childrenOf(group.tasks, root.id).filter((task) =>
        ids.has(task.id),
      );
      if (kids.length) hasKids = true;
      const width = Math.max(1, kids.length) * (CARD_W + GAP_X) - GAP_X;
      positions.set(root.id, { x: x + (width - CARD_W) / 2, y: 0 });
      kids.forEach((kid, index) => {
        positions.set(kid.id, {
          x: x + index * (CARD_W + GAP_X),
          y: CARD_H + GAP_Y,
        });
      });
      x += width + GAP_X * 1.2;
    }
    const extraY = hasKids ? CARD_H * 2 + GAP_Y : CARD_H + GAP_Y;
    for (const task of sortedTasks) {
      if (!positions.has(task.id)) {
        positions.set(task.id, { x, y: extraY });
        x += CARD_W + GAP_X;
      }
    }    return {
      positions,
      width: Math.max(x - GAP_X * 1.2, CARD_W),
      height: hasKids ? CARD_H * 2 + GAP_Y : CARD_H,
    };
  }, [group.tasks, sortedTasks]);

  useEffect(() => {
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") onBack();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onBack]);

  useEffect(() => () => window.clearTimeout(collapseTimer.current), []);

  useLayoutEffect(() => {
    const centers = pendingFlip.current;
    if (!spread || !centers) return;
    pendingFlip.current = null;
    const cards = [...flatCardElements.current.entries()];
    cards.forEach(([id, element], index) => {
      const center = centers.get(id);
      if (!center) return;
      const rect = element.getBoundingClientRect();
      const deltaX = center.x - (rect.left + rect.width / 2);
      const deltaY = center.y - (rect.top + rect.height / 2);
      element.style.transition = "none";
      element.style.transform = `translate(${deltaX}px, ${deltaY}px) scale(.85) rotate(${index % 2 ? 2.5 : -2.5}deg)`;
      element.style.opacity = "0";
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          element.style.transition = `transform .55s cubic-bezier(.16,.8,.24,1) ${index * 26}ms, opacity .35s ease ${index * 26}ms`;
          element.style.transform = "";
          element.style.opacity = "";
          window.setTimeout(() => {
            element.style.transition = "";
          }, 700 + index * 26);
        }),
      );
    });
  }, [spread]);

  function measurePiles() {
    pileCardElements.current.forEach((element, id) => {
      const rect = element.getBoundingClientRect();
      pileCenters.current.set(id, {
        x: rect.left + rect.width / 2,
        y: rect.top + rect.height / 2,
      });
    });
  }

  function spreadPiles() {
    measurePiles();
    setTooltip(null);
    pendingFlip.current = new Map(pileCenters.current);
    setHasSpread(true);
    setSpread(true);
  }

  function collapsePiles() {
    let index = 0;
    flatCardElements.current.forEach((element, id) => {
      const center = pileCenters.current.get(id);
      if (!center) return;
      const rect = element.getBoundingClientRect();
      const deltaX = center.x - (rect.left + rect.width / 2);
      const deltaY = center.y - (rect.top + rect.height / 2);
      element.style.transition = `transform .45s cubic-bezier(.5,.1,.6,1) ${index * 12}ms, opacity .4s ease ${index * 12 + 80}ms`;
      element.style.transform = `translate(${deltaX}px, ${deltaY}px) scale(.85)`;
      element.style.opacity = "0";
      index += 1;
    });
    collapseTimer.current = window.setTimeout(() => setSpread(false), 640);
  }

  const childCount = group.tasks.filter((task) => task.parent_id).length;
  const showFlat = !canPile || spread;
  const shouldRise = showFlat && !hasSpread;

  return (
    <section className="task-detail">
      <header className="task-detail-head">
        <button type="button" className="task-back" onClick={onBack}>
          <ChevronLeft size={14} /> 总览
        </button>
        <div className="task-detail-title">
          <h2>{group.name}</h2>
          <span>
            {group.tasks.length} 个任务 · 其中 {childCount} 个子任务
          </span>
        </div>
        <div className="task-detail-ctrls">
          <div className="task-sort">
            排序
            {(
              [
                ["priority", "优先级"],
                ["due", "截止时间"],
                ["status", "状态"],
              ] as Array<[SortKey, string]>
            ).map(([value, label]) => (
              <button
                type="button"
                key={value}
                className={sortKey === value ? "active" : ""}
                onClick={() => setSortKey(value)}
              >
                {label}
              </button>
            ))}
          </div>
          {canPile ? (
            <div className="task-sort">
              视图
              <button
                type="button"
                className={!showFlat ? "active" : ""}
                onClick={() => {
                  if (showFlat) collapsePiles();
                }}
              >
                堆叠
              </button>
              <button
                type="button"
                className={showFlat ? "active" : ""}
                onClick={() => {
                  if (!showFlat) spreadPiles();
                }}
              >
                摊开
              </button>
            </div>
          ) : null}
          <span className="task-detail-hint">
            {canPile
              ? showFlat
                ? "双击空白处收起 · 单击卡片查看详情"
                : "双击任务堆摊开 · 单击卡片查看详情"
              : "单击卡片查看详情"}
          </span>
        </div>
      </header>

      {showFlat ? (
        <FlatCanvas
          tasks={sortedTasks}
          layout={layout}
          userNames={userNames}
          rise={shouldRise}
          registerCard={registerFlatCard}
          onOpenTask={onOpenTask}
          onBlankDoubleClick={canPile ? collapsePiles : undefined}
        />
      ) : (
        <PileCanvas
          tasks={sortedTasks}
          group={group}
          userNames={userNames}
          registerCard={registerPileCard}
          onOpenTask={onOpenTask}
          onSpread={spreadPiles}
          onTooltip={setTooltip}
        />
      )}

      {tooltip ? (
        <div
          className="task-tip"
          style={{ left: tooltip.x, top: tooltip.y }}
          role="tooltip"
        >
          {tooltip.text}
        </div>
      ) : null}
    </section>
  );
}

function FlatCanvas({
  tasks,
  layout,
  userNames,
  rise,
  registerCard,
  onOpenTask,
  onBlankDoubleClick,
}: {
  tasks: Task[];
  layout: {
    positions: Map<string, { x: number; y: number }>;
    width: number;
    height: number;
  };
  userNames: Map<string, string>;
  rise: boolean;
  registerCard: (id: string, element: HTMLDivElement | null) => void;
  onOpenTask: (task: Task) => void;
  onBlankDoubleClick?: () => void;
}) {
  const ids = new Set(tasks.map((task) => task.id));
  return (
    <div
      className="task-canvas-scroll"
      onDoubleClick={(event) => {
        if (
          onBlankDoubleClick &&
          !(event.target as Element).closest(".task-fcard")
        ) {
          onBlankDoubleClick();
        }
      }}
    >
      <div
        className="task-canvas"
        style={{ width: layout.width, height: layout.height }}
      >
        <svg
          className="task-wire"
          width={layout.width}
          height={layout.height}
          aria-hidden="true"
        >
          {tasks
            .filter(
              (task) =>
                task.parent_id &&
                ids.has(task.parent_id) &&
                layout.positions.has(task.parent_id),
            )
            .map((task) => {
              const from = layout.positions.get(task.parent_id as string);
              const to = layout.positions.get(task.id);
              if (!from || !to) return null;
              const x1 = from.x + CARD_W / 2;
              const y1 = from.y + CARD_H;
              const x2 = to.x + CARD_W / 2;
              const y2 = to.y;
              const midY = (y1 + y2) / 2;
              return (
                <g key={`wire-${task.id}`}>
                  <path
                    d={`M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2 - 6}`}
                    fill="none"
                  />
                  <circle cx={x2} cy={y2 - 4} r="3" />
                </g>
              );
            })}
        </svg>
        {tasks.map((task, index) => {
          const position = layout.positions.get(task.id);
          if (!position) return null;
          return (
            <div
              key={task.id}
              ref={(element) => registerCard(task.id, element)}
              className={`task-fcard${rise ? " task-rise" : ""}`}
              style={{
                left: position.x,
                top: position.y,
                animationDelay: rise ? `${index * 45}ms` : undefined,
              }}
              role="button"
              tabIndex={0}
              onClick={() => onOpenTask(task)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onOpenTask(task);
                }
              }}
            >
              <strong className="tf-name">{task.title}</strong>
              <span className="tf-meta">
                <span>{userNames.get(task.owner_id) ?? "未知用户"}</span>
                <span>
                  {task.due_date ? `截止 ${task.due_date.slice(5)}` : "无截止"}
                </span>
              </span>
              <span className="tf-foot">
                <i
                  className="tf-dot"
                  style={{ background: PRIORITY_COLORS[task.priority] }}
                />
                {PRIORITY_LABELS[task.priority]} · {STATUS_LABELS[task.status]}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PileCanvas({
  tasks,
  group,
  userNames,
  registerCard,
  onOpenTask,
  onSpread,
  onTooltip,
}: {
  tasks: Task[];
  group: TaskGroup;
  userNames: Map<string, string>;
  registerCard: (id: string, element: HTMLDivElement | null) => void;
  onOpenTask: (task: Task) => void;
  onSpread: () => void;
  onTooltip: (
    tooltip: { x: number; y: number; text: string } | null,
  ) => void;
}) {
  const ids = new Set(tasks.map((task) => task.id));
  const roots = tasks.filter(
    (task) => !task.parent_id || !ids.has(task.parent_id),
  );
  return (
    <div
      className="task-piles"
      onDoubleClick={(event) => {
        if (!(event.target as Element).closest(".task-pcard")) onSpread();
      }}
    >
      {roots.map((root) => {
        const kids = childrenOf(group.tasks, root.id).filter((task) =>
          ids.has(task.id),
        );
        const width = PILE_W + (kids.length ? kids.length * PILE_DX + 8 : 0);
        return (
          <div className="task-pile" key={root.id}>
            <div
              className="task-pile-body"
              style={{ width, height: 118 + (kids.length ? 16 : 0) }}
            >
              {[...kids].reverse().map((kid, reversedIndex) => {
                const index = kids.length - 1 - reversedIndex;
                return (
                  <PileCard
                    key={kid.id}
                    task={kid}
                    userNames={userNames}
                    offsetX={(index + 1) * PILE_DX}
                    offsetY={6 + index * 2}
                    rotate={2.5}
                    zIndex={kids.length - index}
                    registerCard={registerCard}
                    onOpenTask={onOpenTask}
                    onSpread={onSpread}
                    onTooltip={onTooltip}
                  />
                );
              })}
              <PileCard
                task={root}
                userNames={userNames}
                offsetX={0}
                offsetY={0}
                rotate={0}
                zIndex={kids.length + 1}
                registerCard={registerCard}
                onOpenTask={onOpenTask}
                onSpread={onSpread}
                onTooltip={onTooltip}
              />
            </div>
            <p className="task-pile-cap">
              <b>{root.title}</b>
              {kids.length ? ` · ${kids.length} 个子任务` : ""}
            </p>
          </div>
        );
      })}
    </div>
  );
}

function PileCard({
  task,
  userNames,
  offsetX,
  offsetY,
  rotate,
  zIndex,
  registerCard,
  onOpenTask,
  onSpread,
  onTooltip,
}: {
  task: Task;
  userNames: Map<string, string>;
  offsetX: number;
  offsetY: number;
  rotate: number;
  zIndex: number;
  registerCard: (id: string, element: HTMLDivElement | null) => void;
  onOpenTask: (task: Task) => void;
  onSpread: () => void;
  onTooltip: (
    tooltip: { x: number; y: number; text: string } | null,
  ) => void;
}) {
  const owner = userNames.get(task.owner_id) ?? "未知用户";
  return (
    <div
      ref={(element) => registerCard(task.id, element)}
      className="task-pcard"
      style={
        {
          zIndex,
          "--tx": `${offsetX}px`,
          "--ty": `${offsetY}px`,
          "--r": `${rotate}deg`,
        } as CSSProperties
      }
      role="button"
      tabIndex={0}
      onClick={() => onOpenTask(task)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpenTask(task);
        }
      }}
      onDoubleClick={(event) => {
        event.stopPropagation();
        onSpread();
      }}
      onMouseEnter={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        onTooltip({
          x: rect.left + rect.width / 2,
          y: rect.top - 8,
          text: `${task.title} · ${owner}`,
        });
      }}
      onMouseLeave={() => onTooltip(null)}
    >
      <strong className="tp-name">{task.title}</strong>
      <span className="tp-meta">
        <span>
          <i
            className="tf-dot"
            style={{ background: PRIORITY_COLORS[task.priority] }}
          />
          {PRIORITY_LABELS[task.priority]}
        </span>
        <span>{owner}</span>
      </span>
    </div>
  );
}

/* ================= 任务详情弹窗 ================= */

export function TaskDetailModal({
  task,
  sourceName,
  childTasks,
  userNames,
  users,
  canManage,
  canCreate,
  transitionActions,
  onClose,
  onEdit,
  onReassign,
  onTransition,
  onProgress,
  onHistory,
  onNewSubtask,
  onDelete,
}: {
  task: Task;
  sourceName: string;
  childTasks: Task[];
  userNames: Map<string, string>;
  users: UserCandidate[];
  canManage: boolean;
  canCreate: boolean;
  transitionActions: Array<{
    status: TaskStatus;
    label: string;
    primary?: boolean;
  }>;
  onClose: () => void;
  onEdit: () => void;
  onReassign: () => void;
  onTransition: (target: TaskStatus) => void;
  onProgress: () => void;
  onHistory: () => void;
  onNewSubtask: () => void;
  onDelete: () => void;
}) {
  const terminal = TERMINAL_STATUSES.has(task.status);
  const collaborators = users.filter((user) =>
    task.collaborator_ids.includes(user.id),
  );
  return (
    <Modal
      title={task.title}
      eyebrow={sourceName}
      onClose={onClose}
      wide
    >
      <div className="modal-form task-detail-modal">
        <div className="task-detail-statusbar">
          <StatusBadge status={task.status} />
          <span className={`priority-label priority-${task.priority}`}>
            {PRIORITY_LABELS[task.priority]} 优先级
          </span>
          {task.level > 0 ? (
            <span className="task-level-tag">L{task.level + 1} 子任务</span>
          ) : null}
        </div>
        <p className="task-detail-desc">
          {task.description || "暂未填写任务说明。"}
        </p>
        <dl className="task-detail-grid">
          <div>
            <dt>负责人</dt>
            <dd>{userNames.get(task.owner_id) ?? "未知用户"}</dd>
          </div>
          <div>
            <dt>截止日期</dt>
            <dd>{task.due_date ?? "未设置"}</dd>
          </div>
          <div>
            <dt>创建于</dt>
            <dd>{task.created_at.slice(0, 10)}</dd>
          </div>
          <div>
            <dt>更新于</dt>
            <dd>{task.updated_at.slice(0, 10)}</dd>
          </div>
        </dl>
        {task.progress_enabled ? (
          <div className="task-progress">
            <div className="task-progress-track">
              <div
                className="task-progress-fill"
                style={{ width: `${task.progress_percent ?? 0}%` }}
              />
            </div>
            <span className="task-progress-value">
              {task.progress_percent ?? 0}%
            </span>
          </div>
        ) : null}
        {task.blocker_reason ? (
          <div className="blocker-note">阻塞：{task.blocker_reason}</div>
        ) : null}
        {task.result ? (
          <InlineNotice tone="success">完成结果：{task.result}</InlineNotice>
        ) : null}
        {task.cancel_reason ? (
          <InlineNotice tone="warning">
            取消原因：{task.cancel_reason}
          </InlineNotice>
        ) : null}
        {collaborators.length ? (
          <div className="task-detail-people">
            <span>协作成员</span>
            <div>
              {collaborators.map((user) => (
                <AvatarImage
                  key={user.id}
                  avatarKey={user.avatar_key}
                  displayName={user.display_name}
                  decorative
                />
              ))}
              <small>
                {collaborators
                  .map((user) => user.display_name)
                  .join("、")}
              </small>
            </div>
          </div>
        ) : null}
        {childTasks.length ? (
          <div className="task-detail-children">
            <span>子任务（{childTasks.length}）</span>
            <ul>
              {childTasks.map((child) => (
                <li key={child.id}>
                  <i
                    className="tf-dot"
                    style={{
                      background: TERMINAL_STATUSES.has(child.status)
                        ? "#16b987"
                        : PRIORITY_COLORS[child.priority],
                    }}
                  />
                  {child.title}
                  <small>{STATUS_LABELS[child.status]}</small>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {canManage ? (
          <footer className="modal-actions task-detail-actions">
            <button className="text-button" onClick={onEdit}>
              编辑
            </button>
            <button className="text-button" onClick={onReassign}>
              转派
            </button>
            {transitionActions.map((action) => (
              <button
                key={action.status}
                className={action.primary ? "small-primary" : "text-button"}
                onClick={() => onTransition(action.status)}
              >
                {action.label}
              </button>
            ))}
            {!terminal ? (
              <button className="text-button" onClick={onProgress}>
                更新进度
              </button>
            ) : null}
            {task.progress_enabled ? (
              <button className="text-button" onClick={onHistory}>
                进度历史
              </button>
            ) : null}
            {canCreate && task.level < 2 && !terminal ? (
              <button className="text-button" onClick={onNewSubtask}>
                新建子任务
              </button>
            ) : null}
            <button
              className="text-button"
              style={{ color: "var(--red)" }}
              onClick={onDelete}
            >
              删除
            </button>
          </footer>
        ) : null}
      </div>
    </Modal>
  );
}