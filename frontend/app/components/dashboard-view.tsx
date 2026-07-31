"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { CSSProperties, FormEvent, ReactNode } from "react";
import { api, ApiClientError } from "../api";
import type {
  AttentionStatus,
  BusinessStage,
  Dashboard,
  DashboardProject,
  DashboardTask,
  PermissionKey,
  TeamWeeklySummary,
} from "../types";
import { AvatarImage } from "./avatar";
import { EmptyState, InlineNotice, Modal } from "./ui";
import {
  AlertTriangle,
  Check,
  Layers,
  LogoMark,
  Minus,
  Package,
  Plus,
  Reload,
  Sparkle,
  TrendingUp,
} from "./icons";

type DashboardPage = "opp" | "work" | "overview";
type OpportunityView = "list" | "graph";

const STAGES: Array<{
  id: BusinessStage;
  label: string;
  color: string;
}> = [
  { id: "lead", label: "线索", color: "#93a8bd" },
  { id: "requirement", label: "需求确认", color: "#16a5d9" },
  { id: "solution_exchange", label: "方案交流", color: "#1677ff" },
  { id: "solution_confirm", label: "方案确认", color: "#6b5cff" },
  { id: "poc", label: "POC验证", color: "#16c6d5" },
  { id: "tender", label: "商务招投标", color: "#e98a32" },
  { id: "won", label: "赢单签约", color: "#16b987" },
];

const ATTENTION: Record<
  AttentionStatus,
  { label: string; color: string; background: string }
> = {
  focus: { label: "重点推进", color: "#1677ff", background: "#eaf4ff" },
  steady: { label: "稳步推进", color: "#25846c", background: "#eaf9f4" },
  coordinate: { label: "待协调", color: "#c34e78", background: "#fff0f5" },
};

const PAGE_COPY: Record<
  DashboardPage,
  { label: string; eyebrow: string; title: string; index: string }
> = {
  opp: {
    label: "商机追踪",
    eyebrow: "解决方案部 · 商机驾驶舱",
    title: "商机进展状态，一屏看清",
    index: "01",
  },
  work: {
    label: "工作管理",
    eyebrow: "解决方案部 · 周度工作管理",
    title: "人在、产出在、进展在",
    index: "02",
  },
  overview: {
    label: "周期总览",
    eyebrow: "解决方案部 · 周期总览",
    title: "跨周趋势与团队节奏",
    index: "03",
  },
};

export function DashboardView({
  permissions,
}: {
  permissions: PermissionKey[];
}) {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [selectedWeek, setSelectedWeek] = useState("");
  const [activePage, setActivePage] = useState<DashboardPage>("opp");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedProject, setSelectedProject] =
    useState<DashboardProject | null>(null);
  const [progressProject, setProgressProject] =
    useState<DashboardProject | null>(null);
  const [relationOpen, setRelationOpen] = useState(false);
  const [summary, setSummary] = useState<TeamWeeklySummary | null>(null);
  const canManageTasks = permissions.includes("tasks.manage");
  const canGenerateTeamSummary = permissions.includes(
    "dashboard.team_summary.generate",
  );

  const applyDashboard = useCallback((result: Dashboard) => {
    setDashboard(result);
    setSelectedWeek(result.selected_week.week_start);
    setSummary(result.latest_team_summary);
    setActivePage((current) =>
      result.accessible_pages.includes(current)
        ? current
        : (result.accessible_pages[0] ?? "opp"),
    );
  }, []);

  const load = useCallback(async (weekStart?: string) => {
    setLoading(true);
    setError("");
    try {
      const result = await api.dashboard.get(weekStart);
      applyDashboard(result);
    } catch (caught) {
      setError(errorMessage(caught, "无法读取作战台数据"));
    } finally {
      setLoading(false);
    }
  }, [applyDashboard]);

  useEffect(() => {
    let cancelled = false;
    api.dashboard
      .get()
      .then((result) => {
        if (!cancelled) applyDashboard(result);
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(errorMessage(caught, "无法读取作战台数据"));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [applyDashboard]);

  async function changeWeek(value: string) {
    setSelectedWeek(value);
    await load(value);
  }

  if (loading && !dashboard) {
    return (
      <main className="war-room war-room-loading">
        <div className="war-loading-mark">
          <i />
          <i />
          <i />
        </div>
        <p>正在汇总项目、任务与周报事实…</p>
      </main>
    );
  }

  if (!dashboard) {
    return (
      <main className="view-page">
        <InlineNotice tone="error">{error || "作战台暂时不可用"}</InlineNotice>
        <button className="primary-button" onClick={() => void load()}>
          重新加载
        </button>
      </main>
    );
  }

  const page = PAGE_COPY[activePage];
  return (
    <main className="war-room">
      <header className="war-room-topbar">
        <div className="war-room-title-lockup">
          <span className="war-room-logo">
            <LogoMark size={21} />
          </span>
          <strong>解决方案部门作战台</strong>
        </div>
        <nav className="war-room-tabs" aria-label="作战台视图">
          {dashboard.accessible_pages.map((pageId) => (
            <button
              type="button"
              key={pageId}
              className={activePage === pageId ? "active" : ""}
              onClick={() => setActivePage(pageId)}
            >
              {PAGE_COPY[pageId].label}
            </button>
          ))}
        </nav>
        {activePage !== "overview" ? (
          <select
            className="war-week-select"
            value={selectedWeek}
            onChange={(event) => void changeWeek(event.target.value)}
            aria-label="选择周次"
          >
            {dashboard.weeks.map((week) => (
              <option key={week.week_start} value={week.week_start}>
                {week.label}
                {week.is_current ? " · 当前周" : ""}
              </option>
            ))}
          </select>
        ) : (
          <span className="war-week-range">
            {dashboard.weeks[0]?.label.split("（")[0]} —{" "}
            {dashboard.weeks.at(-1)?.label.split("（")[0]}
          </span>
        )}
      </header>

      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
      <section className="war-room-headline">
        <div>
          <p>{page.eyebrow}</p>
          <h1>{page.title}</h1>
          <span>
            {headlineSubtitle(activePage, dashboard)}
          </span>
        </div>
        {activePage === "opp" ? (
          <div className="war-headline-actions">
            <button
              type="button"
              className="war-secondary-button"
              onClick={() => void copyText(opportunitySummary(dashboard))}
            >
              复制商机摘要
            </button>
            <button
              type="button"
              className="war-primary-button"
              disabled={!dashboard.projects.some((project) => project.can_manage)}
              onClick={() =>
                setProgressProject(
                  dashboard.projects.find((project) => project.can_manage) ??
                    null,
                )
              }
            >
              <Plus size={14} /> 录入进展
            </button>
          </div>
        ) : activePage === "work" ? (
          <button
            type="button"
            className="war-secondary-button"
            onClick={() => void copyText(workSummary(dashboard))}
          >
            复制工作摘要
          </button>
        ) : null}
      </section>

      {activePage === "opp" ? (
        <OpportunityPage
          dashboard={dashboard}
          onSelectProject={setSelectedProject}
          onRecordProgress={setProgressProject}
          onCreateRelation={() => setRelationOpen(true)}
          canManageRelations={canManageTasks}
        />
      ) : null}
      {activePage === "work" ? (
        <WorkPage
          dashboard={dashboard}
          canGenerateSummary={canGenerateTeamSummary}
          onSummary={setSummary}
          onError={setError}
          onReload={() => load(selectedWeek)}
        />
      ) : null}
      {activePage === "overview" ? (
        <OverviewPage dashboard={dashboard} />
      ) : null}
      <span className="war-page-number">
        {page.index} · {page.label}
      </span>

      {selectedProject ? (
        <ProjectDetailModal
          project={selectedProject}
          onClose={() => setSelectedProject(null)}
          onRecord={() => {
            setProgressProject(selectedProject);
            setSelectedProject(null);
          }}
        />
      ) : null}
      {progressProject ? (
        <ProgressModal
          dashboard={dashboard}
          initialProject={progressProject}
          onClose={() => setProgressProject(null)}
          onSaved={async () => {
            setProgressProject(null);
            await load(selectedWeek);
          }}
        />
      ) : null}
      {relationOpen && canManageTasks ? (
        <RelationModal
          dashboard={dashboard}
          onClose={() => setRelationOpen(false)}
          onSaved={async () => {
            setRelationOpen(false);
            await load(selectedWeek);
          }}
        />
      ) : null}
      {summary ? (
        <SummaryModal
          summary={summary}
          onClose={() => setSummary(null)}
        />
      ) : null}
      {loading ? <div className="war-refreshing">正在刷新…</div> : null}
    </main>
  );
}

function OpportunityPage({
  dashboard,
  onSelectProject,
  onRecordProgress,
  onCreateRelation,
  canManageRelations,
}: {
  dashboard: Dashboard;
  onSelectProject: (project: DashboardProject) => void;
  onRecordProgress: (project: DashboardProject) => void;
  onCreateRelation: () => void;
  canManageRelations: boolean;
}) {
  const [view, setView] = useState<OpportunityView>("list");
  const [scope, setScope] = useState<"active" | "all">("active");
  const [attention, setAttention] = useState<AttentionStatus | "all">("all");
  const [search, setSearch] = useState("");
  const canCreateRelation =
    canManageRelations &&
    dashboard.projects.filter(
      (project) => project.can_manage && project.tasks.length > 0,
    ).length >= 2;
  const projects = useMemo(
    () =>
      dashboard.projects.filter((project) => {
        if (scope === "active" && !project.has_week_progress) return false;
        if (attention !== "all" && project.attention_status !== attention) {
          return false;
        }
        if (
          search &&
          ![
            project.name,
            project.type_label,
            ...project.people.map((person) => person.display_name),
          ]
            .join(" ")
            .toLocaleLowerCase()
            .includes(search.toLocaleLowerCase())
        ) {
          return false;
        }
        return true;
      }),
    [attention, dashboard.projects, scope, search],
  );

  return (
    <>
      <div className="war-metric-grid">
        <MetricCard
          tone="blue"
          icon={<Layers size={20} />}
          label="在跟商机"
          value={dashboard.metrics.tracking_count}
          note={`${dashboard.metrics.focus_count} 个重点推进`}
        />
        <MetricCard
          tone="green"
          icon={<TrendingUp size={20} />}
          label="本周阶段推进"
          value={dashboard.metrics.stage_advanced_count}
          note="阶段节点已前移"
        />
        <MetricCard
          tone="purple"
          icon={<Package size={20} />}
          label="新增交付物"
          value={dashboard.metrics.deliverable_count}
          note="来自真实工作记录"
        />
        <MetricCard
          tone="orange"
          icon={<AlertTriangle size={20} />}
          label="待协调"
          value={dashboard.metrics.coordinate_count}
          note="需主管介入"
        />
      </div>
      <div className="war-opportunity-grid">
        <section className="war-panel war-project-panel">
          <header className="war-panel-head">
            <div>
              <h2>{view === "list" ? "商机推进清单" : "商机关系图谱"}</h2>
              <p>
                {view === "list"
                  ? "点击行查看详情 · 阶段节点高亮表示当前进度"
                  : "项目与任务由真实关系生成 · 虚线表示跨项目关联"}
              </p>
            </div>
            <div className="war-panel-tools">
              <Segmented
                value={scope}
                options={[
                  ["active", "本周有进展"],
                  ["all", "所有项目"],
                ]}
                onChange={(value) => setScope(value as "active" | "all")}
              />
              <Segmented
                value={view}
                options={[
                  ["list", "清单视图"],
                  ["graph", "图谱视图"],
                ]}
                onChange={(value) => setView(value as OpportunityView)}
              />
              {view === "graph" ? (
                <button
                  type="button"
                  className="war-tool-button"
                  disabled={!canCreateRelation}
                  onClick={onCreateRelation}
                  title={
                    canCreateRelation
                      ? "连接两个不同项目中的任务"
                      : "需要同时管理至少两个含任务的项目"
                  }
                >
                  <Plus size={13} /> 建立任务关联
                </button>
              ) : null}
              <select
                value={attention}
                onChange={(event) =>
                  setAttention(
                    event.target.value as AttentionStatus | "all",
                  )
                }
                aria-label="关注状态筛选"
              >
                <option value="all">全部状态</option>
                <option value="focus">重点推进</option>
                <option value="steady">稳步推进</option>
                <option value="coordinate">待协调</option>
              </select>
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索商机 / 人员"
                aria-label="搜索商机或人员"
              />
            </div>
          </header>
          {view === "list" ? (
            <ProjectList
              projects={projects}
              onSelect={onSelectProject}
              onRecord={onRecordProgress}
            />
          ) : (
            <ProjectGraph
              projects={projects}
              links={dashboard.task_links}
              onSelect={onSelectProject}
            />
          )}
        </section>
        <aside className="war-side-stack">
          <StageDistribution
            distribution={dashboard.stage_distribution}
          />
          <section className="war-panel war-side-panel">
            <header>
              <h3>本周动态</h3>
            </header>
            <div className="war-feed-list">
              {dashboard.stage_timeline
                .filter(
                  (event) =>
                    event.week_start ===
                    dashboard.selected_week.week_start,
                )
                .slice(0, 5)
                .map((event) => (
                  <article key={event.id}>
                    <i
                      style={{
                        background:
                          ATTENTION[event.attention_status].color,
                      }}
                    />
                    <div>
                      <b>{event.project_name}</b>
                      <p>
                        进入 {stageLabel(event.business_stage)}：
                        {event.summary}
                      </p>
                      <small>本周 · 阶段推进</small>
                    </div>
                  </article>
                ))}
              {dashboard.projects
                .filter(
                  (project) =>
                    project.attention_status === "coordinate",
                )
                .slice(0, 3)
                .map((project) => (
                  <article key={`risk-${project.id}`}>
                    <i style={{ background: "#e94f9b" }} />
                    <div>
                      <b>{project.name}</b>
                      <p>{project.work_summary}</p>
                      <small>本周 · 风险待协调</small>
                    </div>
                  </article>
                ))}
              {!dashboard.stage_timeline.length &&
              !dashboard.projects.some(
                (project) =>
                  project.attention_status === "coordinate",
              ) ? (
                <p className="war-empty-copy">本周暂无阶段变动</p>
              ) : null}
            </div>
          </section>
        </aside>
      </div>
    </>
  );
}

function ProjectList({
  projects,
  onSelect,
  onRecord,
}: {
  projects: DashboardProject[];
  onSelect: (project: DashboardProject) => void;
  onRecord: (project: DashboardProject) => void;
}) {
  if (!projects.length) {
    return (
      <EmptyState
        title="没有符合条件的商机"
        description="切换范围或筛选条件后再试。"
      />
    );
  }
  return (
    <div className="war-project-table">
      <div className="war-project-table-head">
        <span>商机 / 阶段</span>
        <span>本周进展与交付</span>
        <span>当前状态</span>
        <span>人员 / 工时</span>
      </div>
      {projects.map((project) => (
        <article
          key={project.id}
          className="war-project-row"
          onClick={() => onSelect(project)}
        >
          <div>
            <div className="war-project-name">
              <i style={{ background: projectColor(project.id) }} />
              <span>
                <b>{project.name}</b>
                <small>
                  {project.type_label} ·{" "}
                  {stageLabel(project.business_stage)}
                </small>
              </span>
            </div>
            <StageStepper current={project.business_stage} />
          </div>
          <div className="war-progress-copy">
            <b>{project.work_summary}</b>
            <small>输出：{project.output_summary}</small>
          </div>
          <AttentionPill value={project.attention_status} />
          <div className="war-people-cell">
            <AvatarStack people={project.people} />
            <span>{formatHours(project.weekly_minutes)}h 本周</span>
            {project.can_manage ? (
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  onRecord(project);
                }}
                title="录入该项目进展"
                aria-label={`录入${project.name}进展`}
              >
                <Plus size={13} />
              </button>
            ) : null}
          </div>
        </article>
      ))}
    </div>
  );
}

function ProjectGraph({
  projects,
  links,
  onSelect,
}: {
  projects: DashboardProject[];
  links: Dashboard["task_links"];
  onSelect: (project: DashboardProject) => void;
}) {
  const layout = useMemo(() => graphLayout(projects), [projects]);
  const [viewport, setViewport] = useState({ x: 0, y: 0, scale: 1 });
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{
    pointerId: number;
    clientX: number;
    clientY: number;
    originX: number;
    originY: number;
  } | null>(null);

  function zoomBy(delta: number) {
    setViewport((current) => ({
      ...current,
      scale: clamp(current.scale + delta, 0.65, 1.8),
    }));
  }

  if (!projects.length) {
    return (
      <EmptyState
        title="暂无图谱节点"
        description="为项目创建任务并录入周进展后，关系图会在这里出现。"
      />
    );
  }
  return (
    <div className="war-graph-wrap">
      <svg
        className={`war-graph-svg${dragging ? " dragging" : ""}`}
        viewBox="0 0 1100 650"
        role="img"
        aria-label="项目与任务关系图"
        onPointerDown={(event) => {
          const target = event.target as Element;
          if (target.closest(".war-project-node, .war-task-node")) return;
          drag.current = {
            pointerId: event.pointerId,
            clientX: event.clientX,
            clientY: event.clientY,
            originX: viewport.x,
            originY: viewport.y,
          };
          event.currentTarget.setPointerCapture(event.pointerId);
          setDragging(true);
        }}
        onPointerMove={(event) => {
          if (!drag.current || drag.current.pointerId !== event.pointerId) {
            return;
          }
          const scaleX = 1100 / event.currentTarget.clientWidth;
          const scaleY = 650 / event.currentTarget.clientHeight;
          setViewport((current) => ({
            ...current,
            x:
              drag.current!.originX +
              (event.clientX - drag.current!.clientX) * scaleX,
            y:
              drag.current!.originY +
              (event.clientY - drag.current!.clientY) * scaleY,
          }));
        }}
        onPointerUp={(event) => {
          if (drag.current?.pointerId === event.pointerId) {
            drag.current = null;
            event.currentTarget.releasePointerCapture(event.pointerId);
            setDragging(false);
          }
        }}
        onPointerCancel={() => {
          drag.current = null;
          setDragging(false);
        }}
        onWheel={(event) => {
          event.preventDefault();
          const rect = event.currentTarget.getBoundingClientRect();
          const pointerX =
            ((event.clientX - rect.left) / rect.width) * 1100;
          const pointerY =
            ((event.clientY - rect.top) / rect.height) * 650;
          setViewport((current) => {
            const nextScale = clamp(
              current.scale * (event.deltaY > 0 ? 0.9 : 1.1),
              0.65,
              1.8,
            );
            const worldX = (pointerX - current.x) / current.scale;
            const worldY = (pointerY - current.y) / current.scale;
            return {
              x: pointerX - worldX * nextScale,
              y: pointerY - worldY * nextScale,
              scale: nextScale,
            };
          });
        }}
      >
        <defs>
          <filter id="war-node-shadow">
            <feDropShadow
              dx="0"
              dy="4"
              stdDeviation="5"
              floodOpacity=".13"
            />
          </filter>
        </defs>
        <g
          transform={`translate(${viewport.x} ${viewport.y}) scale(${viewport.scale})`}
        >
          {layout.taskNodes.map((taskNode) => (
            <line
              key={`edge-${taskNode.task.id}`}
              x1={taskNode.projectX}
              y1={taskNode.projectY}
              x2={taskNode.x}
              y2={taskNode.y}
              className="war-graph-edge"
            />
          ))}
          {links.map((link) => {
            const source = layout.taskById.get(link.source_task_id);
            const target = layout.taskById.get(link.target_task_id);
            if (!source || !target) return null;
            return (
              <g key={link.id}>
                <line
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  className="war-graph-cross-edge"
                />
                <title>{link.label}</title>
              </g>
            );
          })}
          {layout.taskNodes.map((node) => (
            <g
              key={node.task.id}
              transform={`translate(${node.x} ${node.y})`}
              className="war-task-node"
            >
              <circle r="27" />
              <text textAnchor="middle" y="4">
                {node.task.title.slice(0, 4)}
              </text>
              <title>
                {node.task.title} · {node.task.owner_display_name}
              </title>
            </g>
          ))}
          {layout.projectNodes.map((node) => (
            <g
              key={node.project.id}
              transform={`translate(${node.x} ${node.y})`}
              className="war-project-node"
              onClick={() => onSelect(node.project)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(node.project);
                }
              }}
              role="button"
              tabIndex={0}
            >
              <circle
                r="54"
                fill="#fff"
                stroke={projectColor(node.project.id)}
                filter="url(#war-node-shadow)"
              />
              <text textAnchor="middle" y="-7">
                {node.project.name.slice(0, 7)}
              </text>
              <text textAnchor="middle" y="15" className="war-node-sub">
                {stageLabel(node.project.business_stage)}
              </text>
            </g>
          ))}
        </g>
      </svg>
      <div className="war-graph-controls" aria-label="图谱缩放控制">
        <button type="button" onClick={() => zoomBy(0.15)} aria-label="放大">
          <Plus size={14} />
        </button>
        <button type="button" onClick={() => zoomBy(-0.15)} aria-label="缩小">
          <Minus size={14} />
        </button>
        <button
          type="button"
          onClick={() => setViewport({ x: 0, y: 0, scale: 1 })}
          aria-label="重置视图"
        >
          <Reload size={13} />
        </button>
      </div>
      <span className="war-graph-hint">拖动画布 · 滚轮缩放</span>
      <div className="war-graph-legend">
        <span><i className="project" />项目节点</span>
        <span><i className="task" />任务节点</span>
        <span><i className="relation" />跨项目关联</span>
      </div>
    </div>
  );
}

function WorkPage({
  dashboard,
  canGenerateSummary,
  onSummary,
  onError,
  onReload,
}: {
  dashboard: Dashboard;
  canGenerateSummary: boolean;
  onSummary: (summary: TeamWeeklySummary) => void;
  onError: (message: string) => void;
  onReload: () => Promise<void>;
}) {
  const [summaryBusy, setSummaryBusy] = useState(false);
  const allSubmitted =
    dashboard.metrics.member_count > 0 &&
    dashboard.metrics.submitted_count === dashboard.metrics.member_count;

  async function generateSummary(force: boolean) {
    setSummaryBusy(true);
    onError("");
    try {
      const generated = await api.dashboard.generateTeamSummary(
        dashboard.selected_week.week_start,
        force,
      );
      onSummary(generated);
      await onReload();
    } catch (caught) {
      onError(errorMessage(caught, "团队周报生成失败"));
    } finally {
      setSummaryBusy(false);
    }
  }

  return (
    <div className="war-work-grid">
      <div className="war-work-main">
        <section className="war-panel war-band-panel">
          <header><h3>团队成员 · 周报提交状态</h3></header>
          <div className="war-member-band">
            {dashboard.members.map((member) => (
              <article key={member.id}>
                <i className={member.submitted ? "on" : ""} />
                <AvatarImage
                  avatarKey={member.avatar_key}
                  displayName={member.display_name}
                  decorative
                />
                <span>
                  <b>{member.display_name}</b>
                  <small>{member.submitted ? "已提交" : "待提交"}</small>
                  <em>
                    {member.submitted
                      ? `${formatHours(member.weekly_minutes)}h 本周工时`
                      : "尚未形成正式版本"}
                  </em>
                </span>
              </article>
            ))}
            <div
              className="war-submit-ring"
              style={
                {
                  "--ring-pct": dashboard.metrics.member_count
                    ? Math.round(
                        (dashboard.metrics.submitted_count /
                          dashboard.metrics.member_count) *
                          100,
                      )
                    : 0,
                } as CSSProperties
              }
            >
              <b>
                {dashboard.metrics.submitted_count}/
                {dashboard.metrics.member_count}
              </b>
              <span>已提交</span>
            </div>
          </div>
        </section>

        <section className="war-panel war-band-panel">
          <header><h3>本周产出 · 交付物</h3></header>
          <div className="war-deliverable-band">
            {dashboard.deliverables.length ? (
              dashboard.deliverables.map((deliverable) => (
                <a
                  key={deliverable.id}
                  href={deliverable.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  <b>{deliverable.name}</b>
                  <span>{deliverable.project_name}</span>
                  <small>
                    {deliverable.author_display_name ?? "团队成员"}
                  </small>
                </a>
              ))
            ) : (
              <p className="war-empty-copy">
                本周暂无已登记交付物
              </p>
            )}
          </div>
        </section>

        <section className="war-panel war-band-panel">
          <header><h3>项目进展 · 本周活跃项目</h3></header>
          <div className="war-project-columns">
            {dashboard.projects
              .filter((project) => project.has_week_progress)
              .map((project) => (
                <article
                  key={project.id}
                  style={{
                    "--project-accent": projectColor(project.id),
                  } as CSSProperties}
                >
                  <header>
                    <b>{project.name}</b>
                    <span>
                      {stageLabel(project.business_stage)}
                      <AttentionPill value={project.attention_status} />
                    </span>
                  </header>
                  <div className="war-project-column-body">
                    {project.work_items.length ? (
                      project.work_items.map((item) => (
                        <div key={item.id}>
                          <AvatarImage
                            avatarKey={item.author_avatar_key}
                            displayName={item.author_display_name}
                            decorative
                          />
                          <span>{item.content}</span>
                        </div>
                      ))
                    ) : (
                      <div>
                        <span>{project.work_summary}</span>
                      </div>
                    )}
                  </div>
                  <footer>
                    <span>
                      阶段进度 <b>{project.progress_percent}%</b>
                    </span>
                    <i>
                      <em
                        style={{ width: `${project.progress_percent}%` }}
                      />
                    </i>
                    <div>
                      <AvatarStack people={project.people} />
                      <b>
                        {formatHours(project.weekly_minutes)}h 本周
                      </b>
                    </div>
                  </footer>
                </article>
              ))}
            {!dashboard.projects.some(
              (project) => project.has_week_progress,
            ) ? (
              <EmptyState
                title="本周暂无活跃项目"
                description="录入工作记录或项目周进展后会自动生成项目列。"
              />
            ) : null}
          </div>
        </section>
      </div>

      <aside className="war-panel war-ai-card">
        <div className="war-ai-title">
          <span>
            <Sparkle size={18} />
          </span>
          <div>
            <h3>团队周报 AI 汇总</h3>
            <p>按成员正式提交版本自动聚合</p>
          </div>
        </div>
        <p>
          汇总本周全部成员周报，提取项目进展、交付物、风险和下周行动。
          生成结果由后端保存，可追溯模型与提交范围。
        </p>
        <div className="war-ai-progress-label">
          <span>周报提交进度</span>
          <b>
            {dashboard.metrics.submitted_count}/
            {dashboard.metrics.member_count}
          </b>
        </div>
        <div className="war-ai-track">
          <i
            style={{
              width: `${
                dashboard.metrics.member_count
                  ? (dashboard.metrics.submitted_count /
                      dashboard.metrics.member_count) *
                    100
                  : 0
              }%`,
            }}
          />
        </div>
        {canGenerateSummary ? (
          <>
            <button
              type="button"
              className="war-ai-button"
              disabled={!allSubmitted || summaryBusy}
              onClick={() => void generateSummary(false)}
            >
              {summaryBusy ? "正在生成…" : "生成团队周报"}
            </button>
            {!allSubmitted && dashboard.metrics.submitted_count > 0 ? (
              <button
                type="button"
                className="war-force-summary"
                disabled={summaryBusy}
                onClick={() => void generateSummary(true)}
              >
                按已提交内容直接生成
              </button>
            ) : null}
          </>
        ) : (
          <p className="war-ai-permission">
            团队负责人完成汇总后，可在此查看正式版本。
          </p>
        )}
        {allSubmitted ? (
          <div className="war-ai-hint ready">
            <Check size={12} /> 全员已提交，可生成本周团队周报
          </div>
        ) : (
          <div className="war-ai-hint">
            等待 {dashboard.metrics.member_count -
              dashboard.metrics.submitted_count}{" "}
            位成员提交
          </div>
        )}
        {dashboard.latest_team_summary ? (
          <button
            type="button"
            className="war-summary-history"
            onClick={() =>
              onSummary(dashboard.latest_team_summary as TeamWeeklySummary)
            }
          >
            查看最近一次汇总 ·{" "}
            {new Date(
              dashboard.latest_team_summary.created_at,
            ).toLocaleString("zh-CN")}
          </button>
        ) : null}
      </aside>
    </div>
  );
}

function OverviewPage({ dashboard }: { dashboard: Dashboard }) {
  const totalMinutes = dashboard.trends.reduce(
    (sum, item) => sum + item.total_minutes,
    0,
  );
  const deliverableCount = dashboard.trends.reduce(
    (sum, item) => sum + item.deliverable_count,
    0,
  );
  return (
    <>
      <div className="war-metric-grid">
        <MetricCard
          tone="blue"
          icon={<Layers size={20} />}
          label="覆盖周数"
          value={dashboard.trends.length}
          note="连续自然周"
        />
        <MetricCard
          tone="green"
          icon={<TrendingUp size={20} />}
          label="累计工时"
          value={`${formatHours(totalMinutes)}h`}
          note="来自工作记录"
        />
        <MetricCard
          tone="purple"
          icon={<Package size={20} />}
          label="累计交付物"
          value={deliverableCount}
          note="真实登记产出"
        />
        <MetricCard
          tone="orange"
          icon={<AlertTriangle size={20} />}
          label="在推进商机"
          value={
            dashboard.projects.filter(
              (project) => project.attention_status !== "coordinate",
            ).length
          }
          note="当前周口径"
        />
      </div>
      <div className="war-overview-grid">
        <section className="war-panel war-trend-panel">
          <header>
            <h3>周次趋势</h3>
            <span>柱：工时 · 线：交付物</span>
          </header>
          <TrendChart dashboard={dashboard} />
        </section>
        <section className="war-panel war-matrix-panel">
          <header><h3>成员 × 周 提交矩阵</h3></header>
          <div className="war-submit-matrix">
            <div className="war-matrix-head">
              <span>成员</span>
              {dashboard.weeks.map((week) => (
                <b key={week.week_start}>{shortWeekLabel(week.label)}</b>
              ))}
              <b>提交率</b>
            </div>
            {dashboard.members.map((member) => (
              <div key={member.id}>
                <span>
                  <AvatarImage
                    avatarKey={member.avatar_key}
                    displayName={member.display_name}
                    decorative
                  />
                  {member.display_name}
                </span>
                {dashboard.weeks.map((week) => (
                  <i
                    key={week.week_start}
                    className={
                      member.submitted_weeks.includes(week.week_start)
                        ? "submitted"
                        : ""
                    }
                  >
                    {member.submitted_weeks.includes(week.week_start) ? (
                      <Check size={12} />
                    ) : (
                      "—"
                    )}
                  </i>
                ))}
                <b>
                  {Math.round(
                    (member.submitted_weeks.length /
                      dashboard.weeks.length) *
                      100,
                  )}
                  %
                </b>
              </div>
            ))}
          </div>
        </section>
        <StageDistribution
          distribution={dashboard.stage_distribution}
          overview
        />
        <section className="war-panel war-timeline-panel">
          <header><h3>阶段推进时间线</h3></header>
          <div>
            {dashboard.stage_timeline.map((event) => (
              <article key={event.id}>
                <b>{dashboardWeekLabel(dashboard, event.week_start)}</b>
                <span>
                  {event.project_name}：进入{" "}
                  {stageLabel(event.business_stage)}
                </span>
              </article>
            ))}
            {!dashboard.stage_timeline.length ? (
              <p className="war-empty-copy">近五周暂无阶段推进记录</p>
            ) : null}
          </div>
        </section>
      </div>
    </>
  );
}

function TrendChart({ dashboard }: { dashboard: Dashboard }) {
  const width = 620;
  const height = 270;
  const floor = 36;
  const chartHeight = 190;
  const maxMinutes = Math.max(
    ...dashboard.trends.map((item) => item.total_minutes),
    60,
  );
  const maxDeliverables = Math.max(
    ...dashboard.trends.map((item) => item.deliverable_count),
    1,
  );
  const step = width / dashboard.trends.length;
  const points = dashboard.trends
    .map((item, index) => {
      const x = step * index + step / 2;
      const y =
        height -
        floor -
        (item.deliverable_count / maxDeliverables) * chartHeight;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg
      className="war-trend-chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="近五周工时与交付物趋势"
    >
      {[0, 0.33, 0.66, 1].map((ratio) => (
        <line
          key={ratio}
          x1="20"
          x2={width - 20}
          y1={height - floor - ratio * chartHeight}
          y2={height - floor - ratio * chartHeight}
          className="war-chart-grid"
        />
      ))}
      {dashboard.trends.map((item, index) => {
        const barHeight = (item.total_minutes / maxMinutes) * chartHeight;
        const x = step * index + step / 2;
        return (
          <g key={item.week_start}>
            <rect
              x={x - 20}
              y={height - floor - barHeight}
              width="40"
              height={barHeight}
              rx="7"
              className="war-chart-bar"
            />
            <text x={x} y={height - 12} textAnchor="middle">
              {dashboardWeekLabel(dashboard, item.week_start)}
            </text>
            <text
              x={x}
              y={height - floor - barHeight - 8}
              textAnchor="middle"
              className="war-chart-value"
            >
              {formatHours(item.total_minutes)}h
            </text>
          </g>
        );
      })}
      <polyline points={points} className="war-chart-line" />
      {dashboard.trends.map((item, index) => {
        const x = step * index + step / 2;
        const y =
          height -
          floor -
          (item.deliverable_count / maxDeliverables) * chartHeight;
        return (
          <g key={`point-${item.week_start}`}>
            <circle cx={x} cy={y} r="5" className="war-chart-point" />
            <text
              x={x}
              y={y - 10}
              textAnchor="middle"
              className="war-chart-deliverables"
            >
              {item.deliverable_count}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function StageDistribution({
  distribution,
  overview = false,
}: {
  distribution: Dashboard["stage_distribution"];
  overview?: boolean;
}) {
  const max = Math.max(...distribution.map((item) => item.count), 1);
  return (
    <section
      className={`war-panel war-stage-panel${overview ? " overview" : ""}`}
    >
      <header>
        <h3>
          商机阶段分布{" "}
          {overview ? <small>（当前周）</small> : null}
        </h3>
      </header>
      <div>
        {distribution.map((item) => {
          const stage = STAGES.find((entry) => entry.id === item.business_stage);
          return (
            <p key={item.business_stage}>
              <span>{stage?.label}</span>
              <i>
                <em
                  style={{
                    width: `${item.count ? Math.max((item.count / max) * 100, 7) : 0}%`,
                    background: stage?.color,
                  }}
                />
              </i>
              <b>{item.count}</b>
            </p>
          );
        })}
      </div>
    </section>
  );
}

function ProjectDetailModal({
  project,
  onClose,
  onRecord,
}: {
  project: DashboardProject;
  onClose: () => void;
  onRecord: () => void;
}) {
  return (
    <Modal
      title={project.name}
      eyebrow={`${project.type_label} · ${ATTENTION[project.attention_status].label}`}
      onClose={onClose}
      wide
    >
      <div className="war-project-detail">
        <section>
          <header>
            <h3>
              当前阶段 · {stageLabel(project.business_stage)}
            </h3>
            <AttentionPill value={project.attention_status} />
          </header>
          <StageStepper current={project.business_stage} />
          <div className="war-detail-progress">
            <span>完成度</span>
            <i>
              <em style={{ width: `${project.progress_percent}%` }} />
            </i>
            <b>{project.progress_percent}%</b>
          </div>
        </section>
        <section>
          <h3>本周进展与交付</h3>
          <p>{project.work_summary}</p>
          <p>输出：{project.output_summary}</p>
        </section>
        <section>
          <h3>关联任务</h3>
          <div className="war-detail-task-list">
            {project.tasks.map((task) => (
              <article key={task.id}>
                <AvatarImage
                  avatarKey={task.owner_avatar_key}
                  displayName={task.owner_display_name}
                  decorative
                />
                <span>
                  <b>{task.title}</b>
                  <small>
                    {task.owner_display_name} · {taskStatusLabel(task)}
                  </small>
                </span>
              </article>
            ))}
            {!project.tasks.length ? <p>暂无关联任务</p> : null}
          </div>
        </section>
        <section>
          <h3>阶段历史</h3>
          <div className="war-detail-history">
            {project.stage_history.map((event) => (
              <article key={event.id}>
                <b>{isoWeek(event.week_start)}</b>
                <span>
                  进入 {stageLabel(event.business_stage)} ·{" "}
                  {event.progress_percent}%
                </span>
              </article>
            ))}
            {!project.stage_history.length ? <p>尚未录入阶段变化</p> : null}
          </div>
        </section>
        <footer>
          <button className="secondary-button" onClick={onClose}>
            关闭
          </button>
          {project.can_manage ? (
            <button className="primary-button" onClick={onRecord}>
              录入本周进展
            </button>
          ) : null}
        </footer>
      </div>
    </Modal>
  );
}

function ProgressModal({
  dashboard,
  initialProject,
  onClose,
  onSaved,
}: {
  dashboard: Dashboard;
  initialProject: DashboardProject;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [projectId, setProjectId] = useState(initialProject.id);
  const [stage, setStage] = useState<BusinessStage>(
    initialProject.business_stage,
  );
  const [attention, setAttention] = useState<AttentionStatus>(
    initialProject.attention_status,
  );
  const [percent, setPercent] = useState(initialProject.progress_percent);
  const [summary, setSummary] = useState("");
  const [output, setOutput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function selectProject(id: string) {
    setProjectId(id);
    const project = dashboard.projects.find((item) => item.id === id);
    if (!project) return;
    setStage(project.business_stage);
    setAttention(project.attention_status);
    setPercent(project.progress_percent);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.dashboard.recordProgress(projectId, {
        week_start: dashboard.selected_week.week_start,
        business_stage: stage,
        attention_status: attention,
        progress_percent: percent,
        summary: summary.trim(),
        output_summary: output.trim() || null,
      });
      await onSaved();
    } catch (caught) {
      setError(errorMessage(caught, "项目进展保存失败"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="录入项目周进展"
      eyebrow={dashboard.selected_week.label}
      onClose={onClose}
    >
      <form className="war-progress-form" onSubmit={submit}>
        <label>
          <span>项目</span>
          <select
            value={projectId}
            onChange={(event) => selectProject(event.target.value)}
          >
            {dashboard.projects
              .filter((project) => project.can_manage)
              .map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
          </select>
        </label>
        <div>
          <label>
            <span>业务阶段</span>
            <select
              value={stage}
              onChange={(event) =>
                setStage(event.target.value as BusinessStage)
              }
            >
              {STAGES.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>关注状态</span>
            <select
              value={attention}
              onChange={(event) =>
                setAttention(event.target.value as AttentionStatus)
              }
            >
              <option value="focus">重点推进</option>
              <option value="steady">稳步推进</option>
              <option value="coordinate">待协调</option>
            </select>
          </label>
        </div>
        <label>
          <span>阶段完成度 · {percent}%</span>
          <input
            type="range"
            min="0"
            max="100"
            step="1"
            value={percent}
            onChange={(event) => setPercent(Number(event.target.value))}
          />
        </label>
        <label>
          <span>本周主要进展</span>
          <textarea
            required
            minLength={1}
            maxLength={10000}
            rows={5}
            value={summary}
            onChange={(event) => setSummary(event.target.value)}
            placeholder="只记录已经发生的事实、当前风险和明确下一步"
          />
        </label>
        <label>
          <span>本周输出</span>
          <textarea
            maxLength={10000}
            rows={3}
            value={output}
            onChange={(event) => setOutput(event.target.value)}
            placeholder="例如：总体方案 V2、评审纪要；没有可留空"
          />
        </label>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer>
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" disabled={busy}>
            {busy ? "正在保存…" : "保存进展"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function RelationModal({
  dashboard,
  onClose,
  onSaved,
}: {
  dashboard: Dashboard;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const taskOptions = dashboard.projects
    .filter((project) => project.can_manage)
    .flatMap((project) =>
      project.tasks.map((task) => ({ project, task })),
    );
  const initialSource = taskOptions[0];
  const initialTarget = taskOptions.find(
    (item) => item.project.id !== initialSource?.project.id,
  );
  const [sourceTaskId, setSourceTaskId] = useState(
    initialSource?.task.id ?? "",
  );
  const [targetTaskId, setTargetTaskId] = useState(
    initialTarget?.task.id ?? "",
  );
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sourceProjectId = taskOptions.find(
    (item) => item.task.id === sourceTaskId,
  )?.project.id;
  const targetOptions = taskOptions.filter(
    (item) => item.project.id !== sourceProjectId,
  );

  function selectSource(taskId: string) {
    setSourceTaskId(taskId);
    const projectId = taskOptions.find(
      (item) => item.task.id === taskId,
    )?.project.id;
    const nextTarget = taskOptions.find(
      (item) => item.project.id !== projectId,
    );
    setTargetTaskId(nextTarget?.task.id ?? "");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.tasks.createRelation({
        source_task_id: sourceTaskId,
        target_task_id: targetTaskId,
        label: label.trim(),
      });
      await onSaved();
    } catch (caught) {
      setError(errorMessage(caught, "任务关联保存失败"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="建立跨项目任务关联"
      eyebrow="商机关系图谱"
      onClose={onClose}
    >
      <form className="war-relation-form" onSubmit={submit}>
        <p>
          关联只连接两个不同项目中的真实任务，保存后会以虚线显示在关系图谱中。
        </p>
        <label>
          <span>起点任务</span>
          <select
            value={sourceTaskId}
            onChange={(event) => selectSource(event.target.value)}
          >
            {manageableTaskOptions(taskOptions)}
          </select>
        </label>
        <label>
          <span>目标任务</span>
          <select
            value={targetTaskId}
            onChange={(event) => setTargetTaskId(event.target.value)}
          >
            {manageableTaskOptions(targetOptions)}
          </select>
        </label>
        <label>
          <span>关联说明</span>
          <input
            required
            minLength={1}
            maxLength={240}
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder="例如：复用同一数据安全规范"
          />
        </label>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer>
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button
            type="submit"
            className="primary-button"
            disabled={busy || !sourceTaskId || !targetTaskId || !label.trim()}
          >
            {busy ? "保存中…" : "保存关联"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function SummaryModal({
  summary,
  onClose,
}: {
  summary: TeamWeeklySummary;
  onClose: () => void;
}) {
  return (
    <Modal
      title="团队周报 · AI 汇总"
      eyebrow={`${summary.week_start} 至 ${summary.week_end} · ${summary.submitted_count}/${summary.expected_count} 人`}
      onClose={onClose}
      wide
    >
      <div className="war-summary-modal">
        <div>
          <span>{summary.generation_model}</span>
          {summary.forced ? <b>按已提交内容直接生成</b> : <b>全员汇总</b>}
        </div>
        <pre>{summary.content}</pre>
        <footer>
          <button className="secondary-button" onClick={onClose}>
            关闭
          </button>
          <button
            className="primary-button"
            onClick={() => void copyText(summary.content)}
          >
            复制摘要
          </button>
        </footer>
      </div>
    </Modal>
  );
}

function manageableTaskOptions(
  options: Array<{
    project: DashboardProject;
    task: DashboardTask;
  }>,
) {
  const projectIds = [...new Set(options.map((item) => item.project.id))];
  return projectIds.map((projectId) => {
    const project = options.find((item) => item.project.id === projectId)!
      .project;
    return (
      <optgroup key={project.id} label={project.name}>
        {options
          .filter((item) => item.project.id === project.id)
          .map(({ task }) => (
            <option key={task.id} value={task.id}>
              {task.title} · {task.owner_display_name}
            </option>
          ))}
      </optgroup>
    );
  });
}

function MetricCard({
  tone,
  icon,
  label,
  value,
  note,
}: {
  tone: "blue" | "green" | "purple" | "orange";
  icon: ReactNode;
  label: string;
  value: ReactNode;
  note: string;
}) {
  return (
    <article className={`war-panel war-metric-card ${tone}`}>
      <span>{icon}</span>
      <div>
        <small>{label}</small>
        <p>
          <b>{value}</b>
          <em>{note}</em>
        </p>
      </div>
    </article>
  );
}

function Segmented({
  value,
  options,
  onChange,
}: {
  value: string;
  options: Array<[string, string]>;
  onChange: (value: string) => void;
}) {
  return (
    <div className="war-segmented">
      {options.map(([id, label]) => (
        <button
          type="button"
          key={id}
          className={value === id ? "active" : ""}
          onClick={() => onChange(id)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function StageStepper({ current }: { current: BusinessStage }) {
  const currentIndex = STAGES.findIndex((stage) => stage.id === current);
  return (
    <div className="war-stage-stepper" title={stageLabel(current)}>
      {STAGES.map((stage, index) => (
        <span
          key={stage.id}
          className={
            index < currentIndex
              ? "done"
              : index === currentIndex
                ? "current"
                : ""
          }
          style={{
            "--stage-color": STAGES[currentIndex]?.color ?? "#1677ff",
          } as CSSProperties}
        >
          <i />
          {index < STAGES.length - 1 ? <em /> : null}
          {index === currentIndex ? <b>{stage.label}</b> : null}
        </span>
      ))}
    </div>
  );
}

function AttentionPill({ value }: { value: AttentionStatus }) {
  const meta = ATTENTION[value];
  return (
    <span
      className="war-attention-pill"
      style={{ color: meta.color, background: meta.background }}
    >
      <i style={{ background: meta.color }} />
      {meta.label}
    </span>
  );
}

function AvatarStack({
  people,
}: {
  people: DashboardProject["people"];
}) {
  return (
    <span className="war-avatar-stack">
      {people.slice(0, 4).map((person) => (
        <AvatarImage
          key={person.id}
          avatarKey={person.avatar_key}
          displayName={person.display_name}
          decorative
        />
      ))}
      {people.length > 4 ? <b>+{people.length - 4}</b> : null}
    </span>
  );
}

function graphLayout(projects: DashboardProject[]) {
  const centerX = 550;
  const centerY = 315;
  const radiusX = projects.length > 4 ? 360 : 290;
  const radiusY = projects.length > 4 ? 215 : 175;
  const projectNodes = projects.map((project, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(projects.length, 1) - Math.PI / 2;
    return {
      project,
      x: centerX + Math.cos(angle) * radiusX,
      y: centerY + Math.sin(angle) * radiusY,
    };
  });
  const taskNodes: Array<{
    task: DashboardTask;
    x: number;
    y: number;
    projectX: number;
    projectY: number;
  }> = [];
  projectNodes.forEach((node) => {
    node.project.tasks.slice(0, 6).forEach((task, index, tasks) => {
      const angle = (Math.PI * 2 * index) / Math.max(tasks.length, 1);
      taskNodes.push({
        task,
        x: node.x + Math.cos(angle) * 112,
        y: node.y + Math.sin(angle) * 82,
        projectX: node.x,
        projectY: node.y,
      });
    });
  });
  return {
    projectNodes,
    taskNodes,
    taskById: new Map(taskNodes.map((item) => [item.task.id, item])),
  };
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(Math.max(value, minimum), maximum);
}

function headlineSubtitle(page: DashboardPage, dashboard: Dashboard) {
  if (page === "opp") {
    return `本周 ${dashboard.metrics.tracking_count} 个在跟商机，${dashboard.metrics.stage_advanced_count} 个阶段推进，${dashboard.metrics.coordinate_count} 个待协调`;
  }
  if (page === "work") {
    return `${dashboard.selected_week.label} · 周报提交 ${dashboard.metrics.submitted_count}/${dashboard.metrics.member_count}`;
  }
  return `${dashboard.weeks[0]?.label.split("（")[0]} 至 ${dashboard.weeks.at(-1)?.label.split("（")[0]} · 共 ${dashboard.weeks.length} 周`;
}

function stageLabel(stage: BusinessStage) {
  return STAGES.find((item) => item.id === stage)?.label ?? stage;
}

function taskStatusLabel(task: DashboardTask) {
  return (
    {
      todo: "待开始",
      in_progress: "进行中",
      blocked: "阻塞",
      done: "已完成",
      cancelled: "已取消",
    }[task.status] ?? task.status
  );
}

function formatHours(minutes: number) {
  const hours = minutes / 60;
  return Number.isInteger(hours) ? String(hours) : hours.toFixed(1);
}

function isoWeek(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  const target = new Date(Date.UTC(year, month - 1, day));
  const weekday = target.getUTCDay() || 7;
  target.setUTCDate(target.getUTCDate() + 4 - weekday);
  const yearStart = new Date(Date.UTC(target.getUTCFullYear(), 0, 1));
  const week = Math.ceil(
    ((target.getTime() - yearStart.getTime()) / 86400000 + 1) / 7,
  );
  return `W${String(week).padStart(2, "0")}`;
}

function shortWeekLabel(label: string) {
  return label.match(/W\d{2}/)?.[0] ?? label;
}

function dashboardWeekLabel(dashboard: Dashboard, weekStart: string) {
  const week = dashboard.weeks.find(
    (candidate) => candidate.week_start === weekStart,
  );
  return week ? shortWeekLabel(week.label) : isoWeek(weekStart);
}

function projectColor(value: string) {
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

function opportunitySummary(dashboard: Dashboard) {
  return `${dashboard.selected_week.label} · 解决方案部商机摘要\n\n${dashboard.projects
    .map(
      (project) =>
        `【${ATTENTION[project.attention_status].label}】${project.name}（${stageLabel(project.business_stage)} · ${project.progress_percent}%）：${project.work_summary}`,
    )
    .join("\n")}`;
}

function workSummary(dashboard: Dashboard) {
  return `${dashboard.selected_week.label} · 解决方案部工作摘要\n\n${dashboard.members
    .map(
      (member) =>
        `${member.display_name}：${
          member.submitted
            ? `已提交，${formatHours(member.weekly_minutes)}h`
            : "本周未提交"
        }`,
    )
    .join("\n")}`;
}

async function copyText(value: string) {
  await navigator.clipboard.writeText(value);
}

function errorMessage(caught: unknown, fallback: string) {
  return caught instanceof ApiClientError ? caught.message : fallback;
}
