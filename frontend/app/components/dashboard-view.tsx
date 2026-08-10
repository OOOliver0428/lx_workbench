"use client";

import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type {
  CSSProperties,
  FormEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
} from "react";
import { api, ApiClientError } from "../api";
import type {
  AttentionStatus,
  BusinessStage,
  Dashboard,
  DashboardOpportunity,
  DashboardProject,
  DashboardTask,
  PermissionKey,
  ProjectCreationDraft,
  TeamWeeklySummary,
  User,
  UserCandidate,
} from "../types";
import { AvatarImage } from "./avatar";
import { EmptyState, InlineNotice, Modal } from "./ui";
import {
  AlertTriangle,
  Check,
  Close,
  Expand,
  Layers,
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
  currentUser,
  onCreateProjectFromOpportunity,
}: {
  permissions: PermissionKey[];
  currentUser: User;
  onCreateProjectFromOpportunity: (draft: ProjectCreationDraft) => void;
}) {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [selectedWeek, setSelectedWeek] = useState("");
  const [activePage, setActivePage] = useState<DashboardPage>("opp");
  const [slideDirection, setSlideDirection] = useState<"left" | "right">(
    "right",
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedProject, setSelectedProject] =
    useState<DashboardProject | null>(null);
  const [selectedOpportunity, setSelectedOpportunity] =
    useState<DashboardOpportunity | null>(null);
  const [progressOpportunity, setProgressOpportunity] =
    useState<DashboardOpportunity | null>(null);
  const [createOpportunityOpen, setCreateOpportunityOpen] = useState(false);
  const [relationOpen, setRelationOpen] = useState(false);
  const [summary, setSummary] = useState<TeamWeeklySummary | null>(null);
  const canEditTasks = permissions.includes("tasks.edit");
  const canRecordOpportunityProgress = permissions.includes(
    "dashboard.opportunity.progress",
  );
  const canCreateOpportunities = permissions.includes(
    "dashboard.opportunity.create",
  );
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
          <strong>解决方案部门作战台</strong>
        </div>
        <nav className="war-room-tabs" aria-label="作战台视图">
          {dashboard.accessible_pages.map((pageId) => (
            <button
              type="button"
              key={pageId}
              className={activePage === pageId ? "active" : ""}
              onClick={() => {
                const order = dashboard.accessible_pages;
                setSlideDirection(
                  order.indexOf(pageId) < order.indexOf(activePage)
                    ? "left"
                    : "right",
                );
                setActivePage(pageId);
              }}
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
            {dashboard.weeks.some(
              (week) => week.week_start === selectedWeek,
            ) ? null : (
              <option value={selectedWeek}>{selectedWeek}</option>
            )}
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
            {canRecordOpportunityProgress ? (
              <button
                type="button"
                className="war-primary-button"
                disabled={!dashboard.opportunities.some(
                  (opportunity) => opportunity.can_manage,
                )}
                onClick={() =>
                  setProgressOpportunity(
                    dashboard.opportunities.find(
                      (opportunity) => opportunity.can_manage,
                    ) ?? null,
                  )
                }
              >
                <Plus size={14} /> 录入进展
              </button>
            ) : null}
            {canCreateOpportunities ? (
              <button
                type="button"
                className="war-primary-button"
                onClick={() => setCreateOpportunityOpen(true)}
              >
                <Plus size={14} /> 新建商机
              </button>
            ) : null}
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

      <div
        key={activePage}
        className={`war-page-slider slide-${slideDirection}`}
      >
        {activePage === "opp" ? (
          <OpportunityPage
            dashboard={dashboard}
            onSelectOpportunity={setSelectedOpportunity}
            onSelectProject={setSelectedProject}
            onRecordProgress={setProgressOpportunity}
            onCreateProject={onCreateProjectFromOpportunity}
            onCreateRelation={() => setRelationOpen(true)}
            canManageRelations={canEditTasks}
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
      </div>
      <span className="war-page-number">
        {page.index} · {page.label}
      </span>

      {selectedOpportunity ? (
        <OpportunityDetailModal
          opportunity={selectedOpportunity}
          onClose={() => setSelectedOpportunity(null)}
          onRecord={() => {
            setProgressOpportunity(selectedOpportunity);
            setSelectedOpportunity(null);
          }}
          onCreateProject={() => {
            onCreateProjectFromOpportunity(
              opportunityProjectDraft(selectedOpportunity),
            );
            setSelectedOpportunity(null);
          }}
        />
      ) : null}
      {selectedProject ? (
        <ProjectDetailModal
          project={selectedProject}
          onClose={() => setSelectedProject(null)}
        />
      ) : null}
      {progressOpportunity && canRecordOpportunityProgress ? (
        <ProgressModal
          dashboard={dashboard}
          initialOpportunity={progressOpportunity}
          onClose={() => setProgressOpportunity(null)}
          onSaved={async () => {
            setProgressOpportunity(null);
            await load(selectedWeek);
          }}
        />
      ) : null}
      {createOpportunityOpen && canCreateOpportunities ? (
        <OpportunityCreateModal
          currentUser={currentUser}
          onClose={() => setCreateOpportunityOpen(false)}
          onCreated={async () => {
            setCreateOpportunityOpen(false);
            await load(selectedWeek);
          }}
        />
      ) : null}
      {relationOpen && canEditTasks ? (
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
  onSelectOpportunity,
  onSelectProject,
  onRecordProgress,
  onCreateProject,
  onCreateRelation,
  canManageRelations,
}: {
  dashboard: Dashboard;
  onSelectOpportunity: (opportunity: DashboardOpportunity) => void;
  onSelectProject: (project: DashboardProject) => void;
  onRecordProgress: (opportunity: DashboardOpportunity) => void;
  onCreateProject: (draft: ProjectCreationDraft) => void;
  onCreateRelation: () => void;
  canManageRelations: boolean;
}) {
  const [view, setView] = useState<OpportunityView>("list");
  const [opportunityScope, setOpportunityScope] =
    useState<"active" | "all">("all");
  const [graphScope, setGraphScope] = useState<"active" | "all">("active");
  const [attention, setAttention] = useState<AttentionStatus | "all">("all");
  const [search, setSearch] = useState("");
  const [graphFullscreen, setGraphFullscreen] = useState(false);
  const canViewWorkMetrics = dashboard.accessible_pages.includes("work");
  const canCreateRelation =
    canManageRelations &&
    dashboard.projects.filter(
      (project) => project.can_manage && project.tasks.length > 0,
    ).length >= 2;
  const projects = useMemo(
    () =>
      dashboard.projects.filter((project) => {
        if (graphScope === "active" && !project.has_week_progress) return false;
        const linkedOpportunity = dashboard.opportunities.find(
          (opportunity) => opportunity.linked_project_id === project.id,
        );
        if (
          attention !== "all" &&
          linkedOpportunity?.attention_status !== attention
        ) {
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
    [
      attention,
      dashboard.opportunities,
      dashboard.projects,
      graphScope,
      search,
    ],
  );
  const opportunities = useMemo(
    () =>
      dashboard.opportunities.filter((opportunity) => {
        if (opportunityScope === "active" && !opportunity.has_week_progress) {
          return false;
        }
        if (
          attention !== "all" &&
          opportunity.attention_status !== attention
        ) {
          return false;
        }
        if (
          search &&
          ![
            opportunity.name,
            opportunity.code,
            opportunity.customer_name ?? "",
            opportunity.owner_display_name,
            ...opportunity.people.map((person) => person.display_name),
          ]
            .join(" ")
            .toLocaleLowerCase()
            .includes(search.toLocaleLowerCase())
        ) {
          return false;
        }
        return true;
      }),
    [attention, dashboard.opportunities, opportunityScope, search],
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
          value={
            canViewWorkMetrics ? dashboard.metrics.deliverable_count : "—"
          }
          note={
            canViewWorkMetrics ? "来自真实工作记录" : "工作产出未授权"
          }
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
                value={view === "list" ? opportunityScope : graphScope}
                options={[
                  ["active", "本周有进展"],
                  ["all", view === "list" ? "所有商机" : "所有项目"],
                ]}
                onChange={(value) =>
                  view === "list"
                    ? setOpportunityScope(value as "active" | "all")
                    : setGraphScope(value as "active" | "all")
                }
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
              {view === "graph" ? (
                <button
                  type="button"
                  className="war-tool-button"
                  onClick={() => setGraphFullscreen(true)}
                  title="全屏查看商机关系图谱"
                >
                  <Expand size={13} /> 全屏
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
            <OpportunityList
              opportunities={opportunities}
              onSelect={onSelectOpportunity}
              onRecord={onRecordProgress}
              onCreateProject={(opportunity) =>
                onCreateProject(opportunityProjectDraft(opportunity))
              }
            />
          ) : graphScope === "all" ? (
            <GraphScopeHint
              projectCount={projects.length}
              onOpenFullscreen={() => setGraphFullscreen(true)}
              onBackToActive={() => setGraphScope("active")}
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
                      <b>{event.opportunity_name}</b>
                      <p>
                        进入 {stageLabel(event.business_stage)}：
                        {event.summary}
                      </p>
                      <small>本周 · 阶段推进</small>
                    </div>
                  </article>
                ))}
              {dashboard.opportunities
                .filter(
                  (opportunity) =>
                    opportunity.attention_status === "coordinate",
                )
                .slice(0, 3)
                .map((opportunity) => (
                  <article key={`risk-${opportunity.id}`}>
                    <i style={{ background: "#e94f9b" }} />
                    <div>
                      <b>{opportunity.name}</b>
                      <p>{opportunity.work_summary}</p>
                      <small>本周 · 风险待协调</small>
                    </div>
                  </article>
                ))}
              {!dashboard.stage_timeline.length &&
              !dashboard.opportunities.some(
                (opportunity) =>
                  opportunity.attention_status === "coordinate",
              ) ? (
                <p className="war-empty-copy">本周暂无阶段变动</p>
              ) : null}
            </div>
          </section>
        </aside>
      </div>
      {graphFullscreen ? (
        <GraphFullscreen
          projects={projects}
          links={dashboard.task_links}
          scope={graphScope}
          onScopeChange={(value) => setGraphScope(value)}
          onSelectProject={onSelectProject}
          onClose={() => setGraphFullscreen(false)}
          canCreateRelation={canCreateRelation}
          onCreateRelation={onCreateRelation}
        />
      ) : null}
    </>
  );
}

function OpportunityList({
  opportunities,
  onSelect,
  onRecord,
  onCreateProject,
}: {
  opportunities: DashboardOpportunity[];
  onSelect: (opportunity: DashboardOpportunity) => void;
  onRecord: (opportunity: DashboardOpportunity) => void;
  onCreateProject: (opportunity: DashboardOpportunity) => void;
}) {
  if (!opportunities.length) {
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
        <span>人员</span>
      </div>
      {opportunities.map((opportunity) => (
        <article
          key={opportunity.id}
          className="war-project-row"
          onClick={() => onSelect(opportunity)}
        >
          <div>
            <div className="war-project-name">
              <i style={{ background: projectColor(opportunity.id) }} />
              <span>
                <b>{opportunity.name}</b>
                <small>
                  {opportunity.customer_name || opportunity.code} ·{" "}
                  {stageLabel(opportunity.business_stage)}
                </small>
              </span>
            </div>
            <StageStepper current={opportunity.business_stage} />
          </div>
          <div className="war-progress-copy">
            <b>{opportunity.work_summary}</b>
            <small>输出：{opportunity.output_summary}</small>
          </div>
          <AttentionPill value={opportunity.attention_status} />
          <div className="war-people-cell">
            <div className="war-people-summary">
              <AvatarStack people={opportunity.people} />
              <span>
                {opportunity.people
                  .map((person) => person.display_name)
                  .join("、") || opportunity.owner_display_name}
              </span>
            </div>
            <div className="war-people-actions">
              {opportunity.can_convert ? (
                <button
                  type="button"
                  className="war-convert-button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onCreateProject(opportunity);
                  }}
                  title="创建并关联项目"
                  aria-label={`将${opportunity.name}创建并关联项目`}
                >
                  创建项目
                </button>
              ) : null}
              {opportunity.can_manage ? (
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onRecord(opportunity);
                  }}
                  title="录入该商机进展"
                  aria-label={`录入${opportunity.name}进展`}
                >
                  <Plus size={13} />
                </button>
              ) : null}
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}

const GRAPH_DIMS = {
  normal: { width: 1100, height: 650 },
  fullscreen: { width: 1680, height: 920 },
} as const;

type GraphDims = (typeof GRAPH_DIMS)[keyof typeof GRAPH_DIMS];

type GraphProjectNode = {
  project: DashboardProject;
  x: number;
  y: number;
};

type GraphTaskNode = {
  task: DashboardTask;
  projectId: string;
  x: number;
  y: number;
  projectX: number;
  projectY: number;
};

type NodeDownHandler = (
  event: ReactPointerEvent<SVGGElement>,
  key: string,
  projectId: string,
) => void;

type NodeMoveHandler = (event: ReactPointerEvent<SVGGElement>) => void;

type NodeEndHandler = (
  event: ReactPointerEvent<SVGGElement>,
) => boolean | null;

const GraphEdge = memo(function GraphEdge({
  x1,
  y1,
  x2,
  y2,
  dimmed,
}: {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  dimmed: boolean;
}) {
  return (
    <line
      x1={x1}
      y1={y1}
      x2={x2}
      y2={y2}
      className={`war-graph-edge${dimmed ? " war-graph-dim" : ""}`}
    />
  );
});

const GraphCrossEdge = memo(function GraphCrossEdge({
  x1,
  y1,
  x2,
  y2,
  label,
  dimmed,
}: {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  label: string;
  dimmed: boolean;
}) {
  return (
    <g className={dimmed ? "war-graph-dim" : undefined}>
      <line
        x1={x1}
        y1={y1}
        x2={x2}
        y2={y2}
        className="war-graph-cross-edge"
      />
      <title>{label}</title>
    </g>
  );
});

const TaskGraphNode = memo(function TaskGraphNode({
  node,
  x,
  y,
  dimmed,
  onDown,
  onMove,
  onEnd,
  onHover,
}: {
  node: GraphTaskNode;
  x: number;
  y: number;
  dimmed: boolean;
  onDown: NodeDownHandler;
  onMove: NodeMoveHandler;
  onEnd: NodeEndHandler;
  onHover: (projectId: string | null) => void;
}) {
  return (
    <g
      transform={`translate(${x} ${y})`}
      className={`war-task-node${dimmed ? " war-graph-dim" : ""}`}
      onPointerDown={(event) =>
        onDown(event, `t:${node.task.id}`, node.projectId)
      }
      onPointerMove={onMove}
      onPointerUp={onEnd}
      onPointerCancel={onEnd}
      onPointerEnter={() => onHover(node.projectId)}
      onPointerLeave={() => onHover(null)}
    >
      <circle r="27" />
      <text textAnchor="middle" y="4">
        {node.task.title.slice(0, 4)}
      </text>
      <title>
        {node.task.title} · {node.task.owner_display_name}
      </title>
    </g>
  );
});

const ProjectGraphNode = memo(function ProjectGraphNode({
  node,
  x,
  y,
  dimmed,
  onDown,
  onMove,
  onEnd,
  onHover,
  onSelect,
}: {
  node: GraphProjectNode;
  x: number;
  y: number;
  dimmed: boolean;
  onDown: NodeDownHandler;
  onMove: NodeMoveHandler;
  onEnd: NodeEndHandler;
  onHover: (projectId: string | null) => void;
  onSelect: (project: DashboardProject) => void;
}) {
  return (
    <g
      transform={`translate(${x} ${y})`}
      className={`war-project-node${dimmed ? " war-graph-dim" : ""}`}
      onPointerDown={(event) =>
        onDown(event, `p:${node.project.id}`, node.project.id)
      }
      onPointerMove={onMove}
      onPointerUp={(event) => {
        if (onEnd(event) === false) onSelect(node.project);
      }}
      onPointerCancel={onEnd}
      onPointerEnter={() => onHover(node.project.id)}
      onPointerLeave={() => onHover(null)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(node.project);
        }
      }}
      role="button"
      tabIndex={0}
    >
      <rect
        x="-72"
        y="-42"
        width="144"
        height="84"
        rx="18"
        ry="18"
        fill="#fff"
        stroke={projectColor(node.project.id)}
        filter="url(#war-node-shadow)"
      />
      <text textAnchor="middle" y="-7">
        {node.project.name.slice(0, 7)}
      </text>
      <text textAnchor="middle" y="15" className="war-node-sub">
        {projectStatusLabel(node.project.lifecycle_status)}
      </text>
    </g>
  );
});

function GraphScopeHint({
  projectCount,
  onOpenFullscreen,
  onBackToActive,
}: {
  projectCount: number;
  onOpenFullscreen: () => void;
  onBackToActive: () => void;
}) {
  return (
    <div className="war-graph-scope-hint">
      <span className="war-graph-scope-hint-mark" aria-hidden="true">
        <Expand size={22} />
      </span>
      <h3>全部项目图谱请在全屏模式查看</h3>
      <p>
        当前范围包含 {projectCount} 个项目，节点与连线较多，嵌入面板难以完整展示。
        全屏模式提供完整画布，同样支持拖拽排版、悬停聚焦、画布缩放与建立任务关联。
      </p>
      <div className="war-graph-scope-hint-actions">
        <button
          type="button"
          className="war-primary-button"
          onClick={onOpenFullscreen}
        >
          <Expand size={14} /> 进入全屏查看
        </button>
        <button
          type="button"
          className="war-secondary-button"
          onClick={onBackToActive}
        >
          返回本周有进展
        </button>
      </div>
    </div>
  );
}

function GraphFullscreen({
  projects,
  links,
  scope,
  onScopeChange,
  onSelectProject,
  onClose,
  canCreateRelation,
  onCreateRelation,
}: {
  projects: DashboardProject[];
  links: Dashboard["task_links"];
  scope: "active" | "all";
  onScopeChange: (scope: "active" | "all") => void;
  onSelectProject: (project: DashboardProject) => void;
  onClose: () => void;
  canCreateRelation: boolean;
  onCreateRelation: () => void;
}) {
  useEffect(() => {
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", handleKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);
  return (
    <div
      className="war-graph-fullscreen"
      role="dialog"
      aria-modal="true"
      aria-label="商机关系图谱全屏视图"
    >
      <header className="war-graph-fullscreen-head">
        <div className="war-room-title-lockup">
          <strong>商机关系图谱</strong>
        </div>
        <p className="war-graph-fullscreen-sub">
          拖拽节点重新排版 · 悬停节点聚焦本项目 · 拖动画布平移 · 按钮缩放
        </p>
        <div className="war-graph-fullscreen-tools">
          <Segmented
            value={scope}
            options={[
              ["active", "本周有进展"],
              ["all", "所有项目"],
            ]}
            onChange={(value) => onScopeChange(value as "active" | "all")}
          />
          {canCreateRelation ? (
            <button
              type="button"
              className="war-tool-button"
              onClick={onCreateRelation}
            >
              <Plus size={13} /> 建立任务关联
            </button>
          ) : null}
          <button
            type="button"
            className="war-secondary-button"
            onClick={onClose}
          >
            <Close size={14} /> 退出全屏
          </button>
        </div>
      </header>
      <div className="war-graph-fullscreen-body">
        {projects.length ? (
          <ProjectGraph
            projects={projects}
            links={links}
            onSelect={onSelectProject}
            fullscreen
          />
        ) : (
          <EmptyState
            title="暂无图谱节点"
            description="当前范围内没有可展示的项目，切换显示范围或调整筛选后再试。"
          />
        )}
      </div>
    </div>
  );
}

function ProjectGraph({
  projects,
  links,
  onSelect,
  fullscreen = false,
}: {
  projects: DashboardProject[];
  links: Dashboard["task_links"];
  onSelect: (project: DashboardProject) => void;
  fullscreen?: boolean;
}) {
  const dims = fullscreen ? GRAPH_DIMS.fullscreen : GRAPH_DIMS.normal;
  const layout = useMemo(() => graphLayout(projects, dims), [projects, dims]);
  const [viewport, setViewport] = useState({ x: 0, y: 0, scale: 1 });
  const [panning, setPanning] = useState(false);
  const [nodeDragging, setNodeDragging] = useState(false);
  const [offsets, setOffsets] = useState<
    Record<string, { x: number; y: number }>
  >({});
  const [hoverProjectId, setHoverProjectId] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const panDrag = useRef<{
    pointerId: number;
    clientX: number;
    clientY: number;
    originX: number;
    originY: number;
  } | null>(null);
  const nodeDrag = useRef<{
    pointerId: number;
    key: string;
    projectId: string;
    clientX: number;
    clientY: number;
    baseX: number;
    baseY: number;
    moved: boolean;
  } | null>(null);
  const viewportRef = useRef(viewport);
  const offsetsRef = useRef(offsets);
  const offsetFrame = useRef(0);
  const pendingOffset = useRef<{ key: string; x: number; y: number } | null>(
    null,
  );

  useEffect(() => {
    viewportRef.current = viewport;
  }, [viewport]);

  useEffect(() => {
    offsetsRef.current = offsets;
  }, [offsets]);

  const scheduleOffset = useCallback((key: string, x: number, y: number) => {
    pendingOffset.current = { key, x, y };
    if (offsetFrame.current) return;
    offsetFrame.current = window.requestAnimationFrame(() => {
      offsetFrame.current = 0;
      const pending = pendingOffset.current;
      pendingOffset.current = null;
      if (!pending) return;
      setOffsets((current) => {
        const previous = current[pending.key];
        if (previous && previous.x === pending.x && previous.y === pending.y) {
          return current;
        }
        return { ...current, [pending.key]: { x: pending.x, y: pending.y } };
      });
    });
  }, []);

  useEffect(
    () => () => {
      if (offsetFrame.current) {
        window.cancelAnimationFrame(offsetFrame.current);
      }
    },
    [],
  );

  const positions = useMemo(() => {
    const projectPositions = new Map<string, { x: number; y: number }>();
    for (const node of layout.projectNodes) {
      const offset = offsets[`p:${node.project.id}`];
      projectPositions.set(node.project.id, {
        x: node.x + (offset?.x ?? 0),
        y: node.y + (offset?.y ?? 0),
      });
    }
    const taskPositions = new Map<string, { x: number; y: number }>();
    for (const node of layout.taskNodes) {
      const offset = offsets[`t:${node.task.id}`];
      taskPositions.set(node.task.id, {
        x: node.x + (offset?.x ?? 0),
        y: node.y + (offset?.y ?? 0),
      });
    }
    return { projectPositions, taskPositions };
  }, [layout, offsets]);

  const focusTaskIds = useMemo(() => {
    if (!hoverProjectId) return null;
    const taskIds = new Set(
      layout.taskNodes
        .filter((node) => node.projectId === hoverProjectId)
        .map((node) => node.task.id),
    );
    for (const link of links) {
      if (taskIds.has(link.source_task_id)) {
        taskIds.add(link.target_task_id);
      } else if (taskIds.has(link.target_task_id)) {
        taskIds.add(link.source_task_id);
      }
    }
    return taskIds;
  }, [hoverProjectId, layout, links]);

  const handleNodeDown = useCallback<NodeDownHandler>(
    (event, key, projectId) => {
      event.stopPropagation();
      nodeDrag.current = {
        pointerId: event.pointerId,
        key,
        projectId,
        clientX: event.clientX,
        clientY: event.clientY,
        baseX: offsetsRef.current[key]?.x ?? 0,
        baseY: offsetsRef.current[key]?.y ?? 0,
        moved: false,
      };
      event.currentTarget.setPointerCapture(event.pointerId);
      setHoverProjectId(projectId);
      setNodeDragging(true);
    },
    [],
  );

  const handleNodeMove = useCallback<NodeMoveHandler>(
    (event) => {
      const active = nodeDrag.current;
      if (!active || active.pointerId !== event.pointerId) return;
      const svg = svgRef.current;
      if (!svg) return;
      const scale = viewportRef.current.scale;
      const deltaX =
        ((event.clientX - active.clientX) * (dims.width / svg.clientWidth)) /
        scale;
      const deltaY =
        ((event.clientY - active.clientY) * (dims.height / svg.clientHeight)) /
        scale;
      if (!active.moved && Math.hypot(deltaX, deltaY) > 3) {
        active.moved = true;
      }
      if (active.moved) {
        scheduleOffset(active.key, active.baseX + deltaX, active.baseY + deltaY);
      }
    },
    [dims, scheduleOffset],
  );

  const handleNodeEnd = useCallback<NodeEndHandler>((event) => {
    const active = nodeDrag.current;
    if (!active || active.pointerId !== event.pointerId) return null;
    nodeDrag.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
    setNodeDragging(false);
    setHoverProjectId(null);
    return active.moved;
  }, []);

  const handleNodeHover = useCallback((projectId: string | null) => {
    if (nodeDrag.current) return;
    setHoverProjectId(projectId);
  }, []);

  const hasCustomLayout = Object.keys(offsets).length > 0;

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
        ref={svgRef}
        className={`war-graph-svg${panning ? " dragging" : ""}${nodeDragging ? " node-dragging" : ""}`}
        viewBox={`0 0 ${dims.width} ${dims.height}`}
        role="img"
        aria-label="项目与任务关系图"
        onPointerDown={(event) => {
          if (nodeDrag.current) return;
          const target = event.target as Element;
          if (target.closest(".war-project-node, .war-task-node")) return;
          panDrag.current = {
            pointerId: event.pointerId,
            clientX: event.clientX,
            clientY: event.clientY,
            originX: viewport.x,
            originY: viewport.y,
          };
          event.currentTarget.setPointerCapture(event.pointerId);
          setPanning(true);
        }}
        onPointerMove={(event) => {
          if (!panDrag.current || panDrag.current.pointerId !== event.pointerId) {
            return;
          }
          const scaleX = dims.width / event.currentTarget.clientWidth;
          const scaleY = dims.height / event.currentTarget.clientHeight;
          setViewport((current) => ({
            ...current,
            x:
              panDrag.current!.originX +
              (event.clientX - panDrag.current!.clientX) * scaleX,
            y:
              panDrag.current!.originY +
              (event.clientY - panDrag.current!.clientY) * scaleY,
          }));
        }}
        onPointerUp={(event) => {
          if (panDrag.current?.pointerId === event.pointerId) {
            panDrag.current = null;
            event.currentTarget.releasePointerCapture(event.pointerId);
            setPanning(false);
          }
        }}
        onPointerCancel={() => {
          panDrag.current = null;
          setPanning(false);
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
          {layout.taskNodes.map((taskNode) => {
            const projectPosition = positions.projectPositions.get(
              taskNode.projectId,
            );
            const taskPosition = positions.taskPositions.get(taskNode.task.id);
            if (!projectPosition || !taskPosition) return null;
            return (
              <GraphEdge
                key={`edge-${taskNode.task.id}`}
                x1={projectPosition.x}
                y1={projectPosition.y}
                x2={taskPosition.x}
                y2={taskPosition.y}
                dimmed={
                  focusTaskIds !== null &&
                  !focusTaskIds.has(taskNode.task.id)
                }
              />
            );
          })}
          {links.map((link) => {
            const sourcePosition = positions.taskPositions.get(
              link.source_task_id,
            );
            const targetPosition = positions.taskPositions.get(
              link.target_task_id,
            );
            if (!sourcePosition || !targetPosition) return null;
            return (
              <GraphCrossEdge
                key={link.id}
                x1={sourcePosition.x}
                y1={sourcePosition.y}
                x2={targetPosition.x}
                y2={targetPosition.y}
                label={link.label}
                dimmed={
                  focusTaskIds !== null &&
                  !(
                    focusTaskIds.has(link.source_task_id) &&
                    focusTaskIds.has(link.target_task_id)
                  )
                }
              />
            );
          })}
          {layout.taskNodes.map((node) => {
            const position = positions.taskPositions.get(node.task.id);
            if (!position) return null;
            return (
              <TaskGraphNode
                key={node.task.id}
                node={node}
                x={position.x}
                y={position.y}
                dimmed={
                  focusTaskIds !== null && !focusTaskIds.has(node.task.id)
                }
                onDown={handleNodeDown}
                onMove={handleNodeMove}
                onEnd={handleNodeEnd}
                onHover={handleNodeHover}
              />
            );
          })}
          {layout.projectNodes.map((node) => {
            const position = positions.projectPositions.get(node.project.id);
            if (!position) return null;
            return (
              <ProjectGraphNode
                key={node.project.id}
                node={node}
                x={position.x}
                y={position.y}
                dimmed={
                  hoverProjectId !== null &&
                  node.project.id !== hoverProjectId
                }
                onDown={handleNodeDown}
                onMove={handleNodeMove}
                onEnd={handleNodeEnd}
                onHover={handleNodeHover}
                onSelect={onSelect}
              />
            );
          })}
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
      <div className="war-graph-hint">
        <span>拖动画布平移 · 按钮缩放 · 拖拽节点排版 · 悬停聚焦</span>
        {hasCustomLayout ? (
          <button type="button" onClick={() => setOffsets({})}>
            重置排版
          </button>
        ) : null}
      </div>
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
                      ? member.weekly_minutes === null
                        ? "工时不可见"
                        : `${formatHours(member.weekly_minutes)}h 本周工时`
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
                    <span>{projectStatusLabel(project.lifecycle_status)}</span>
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
                    <div>
                      <AvatarStack people={project.people} />
                      <b>
                        {project.weekly_minutes === null
                          ? "工时不可见"
                          : `${formatHours(project.weekly_minutes)}h 本周`}
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
            dashboard.metrics.tracking_count -
            dashboard.metrics.coordinate_count
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
                  {event.opportunity_name}：进入{" "}
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

function OpportunityDetailModal({
  opportunity,
  onClose,
  onRecord,
  onCreateProject,
}: {
  opportunity: DashboardOpportunity;
  onClose: () => void;
  onRecord: () => void;
  onCreateProject: () => void;
}) {
  return (
    <Modal
      title={opportunity.name}
      eyebrow={`${opportunity.code} · ${ATTENTION[opportunity.attention_status].label}`}
      onClose={onClose}
      wide
    >
      <div className="war-project-detail">
        <section>
          <header>
            <h3>当前阶段 · {stageLabel(opportunity.business_stage)}</h3>
            <AttentionPill value={opportunity.attention_status} />
          </header>
          <StageStepper current={opportunity.business_stage} />
          <div className="war-detail-progress">
            <span>完成度</span>
            <i><em style={{ width: `${opportunity.progress_percent}%` }} /></i>
            <b>{opportunity.progress_percent}%</b>
          </div>
        </section>
        <section>
          <h3>商机信息</h3>
          <p>客户：{opportunity.customer_name || "暂未填写"}</p>
          <p>负责人：{opportunity.owner_display_name}</p>
          <p>{opportunity.description || "暂无补充说明"}</p>
        </section>
        <section>
          <h3>本周推进</h3>
          <p>{opportunity.work_summary}</p>
          <p>输出：{opportunity.output_summary}</p>
        </section>
        <section>
          <h3>关联项目</h3>
          <p>
            {opportunity.linked_project_name
              ? `${opportunity.linked_project_code} · ${opportunity.linked_project_name}`
              : opportunity.can_convert
                ? "尚未关联项目，可从当前商机创建并自动关联。"
                : "进入方案交流阶段后可创建关联项目。"}
          </p>
        </section>
        <section>
          <h3>阶段历史</h3>
          <div className="war-detail-history">
            {opportunity.stage_history.map((event) => (
              <article key={event.id}>
                <b>{isoWeek(event.week_start)}</b>
                <span>
                  进入 {stageLabel(event.business_stage)} · {event.progress_percent}%
                </span>
              </article>
            ))}
            {!opportunity.stage_history.length ? <p>尚未录入阶段变化</p> : null}
          </div>
        </section>
        <footer>
          <button className="secondary-button" onClick={onClose}>关闭</button>
          {opportunity.can_manage ? (
            <button className="secondary-button" onClick={onRecord}>
              录入本周进展
            </button>
          ) : null}
          {opportunity.can_convert ? (
            <button className="primary-button" onClick={onCreateProject}>
              创建并关联项目
            </button>
          ) : null}
        </footer>
      </div>
    </Modal>
  );
}

function ProjectDetailModal({
  project,
  onClose,
}: {
  project: DashboardProject;
  onClose: () => void;
}) {
  return (
    <Modal
      title={project.name}
      eyebrow={`${project.type_label} · ${projectStatusLabel(project.lifecycle_status)}`}
      onClose={onClose}
      wide
    >
      <div className="war-project-detail">
        <section>
          <header>
            <h3>项目状态 · {projectStatusLabel(project.lifecycle_status)}</h3>
          </header>
          <p>
            项目节点用于承载任务、工作记录与交付物；商业阶段在关联商机中独立维护。
          </p>
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
        <footer>
          <button className="secondary-button" onClick={onClose}>
            关闭
          </button>
        </footer>
      </div>
    </Modal>
  );
}

function OpportunityCreateModal({
  currentUser,
  onClose,
  onCreated,
}: {
  currentUser: User;
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [users, setUsers] = useState<UserCandidate[]>([]);
  const [ownerId, setOwnerId] = useState(
    currentUser.role === "super_admin" ? "" : currentUser.id,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api.users
      .candidates()
      .then((rows) => {
        if (!cancelled) setUsers(rows);
      })
      .catch((caught) => {
        if (!cancelled) setError(errorMessage(caught, "负责人列表加载失败"));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      await api.opportunities.create({
        name: String(form.get("name") ?? "").trim(),
        customer_name: optionalFormValue(form.get("customer_name")),
        description: optionalFormValue(form.get("description")),
        owner_id: ownerId || null,
        member_ids: form.getAll("member_ids").map(String),
      });
      await onCreated();
    } catch (caught) {
      setError(errorMessage(caught, "商机创建失败"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="新建商机" eyebrow="NEW OPPORTUNITY" onClose={onClose} wide>
      <form className="modal-form" onSubmit={submit}>
        <div className="form-grid">
          <label className="field field-span-two">
            <span>商机名称 *</span>
            <input name="name" required maxLength={200} autoFocus />
          </label>
          <label className="field">
            <span>客户名称</span>
            <input name="customer_name" maxLength={200} />
          </label>
          <label className="field">
            <span>商机负责人 *</span>
            <select
              value={ownerId}
              onChange={(event) => setOwnerId(event.target.value)}
              required
            >
              <option value="" disabled>请选择负责人</option>
              {users.map((user) => (
                <option key={user.id} value={user.id}>{user.display_name}</option>
              ))}
            </select>
          </label>
          <label className="field field-span-two">
            <span>商机说明</span>
            <textarea name="description" rows={4} maxLength={10000} />
          </label>
          <fieldset className="tag-options field-span-two">
            <legend>参与人员</legend>
            {users
              .filter((user) => user.id !== ownerId)
              .map((user) => (
                <label key={user.id}>
                  <input type="checkbox" name="member_ids" value={user.id} />
                  <span>{user.display_name}</span>
                </label>
              ))}
          </fieldset>
        </div>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <footer className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" disabled={busy || !ownerId}>
            {busy ? "正在创建…" : "创建商机"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function ProgressModal({
  dashboard,
  initialOpportunity,
  onClose,
  onSaved,
}: {
  dashboard: Dashboard;
  initialOpportunity: DashboardOpportunity;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [opportunityId, setOpportunityId] = useState(initialOpportunity.id);
  const [stage, setStage] = useState<BusinessStage>(
    initialOpportunity.business_stage,
  );
  const [attention, setAttention] = useState<AttentionStatus>(
    initialOpportunity.attention_status,
  );
  const [percent, setPercent] = useState(initialOpportunity.progress_percent);
  const [summary, setSummary] = useState("");
  const [output, setOutput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function selectOpportunity(id: string) {
    setOpportunityId(id);
    const opportunity = dashboard.opportunities.find((item) => item.id === id);
    if (!opportunity) return;
    setStage(opportunity.business_stage);
    setAttention(opportunity.attention_status);
    setPercent(opportunity.progress_percent);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const opportunity = dashboard.opportunities.find(
        (item) => item.id === opportunityId,
      );
      if (!opportunity) throw new Error("商机不存在");
      await api.dashboard.recordProgress(opportunityId, {
        revision: opportunity.revision,
        week_start: dashboard.selected_week.week_start,
        business_stage: stage,
        attention_status: attention,
        progress_percent: percent,
        summary: summary.trim(),
        output_summary: output.trim() || null,
      });
      await onSaved();
    } catch (caught) {
      setError(errorMessage(caught, "商机进展保存失败"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="录入商机周进展"
      eyebrow={dashboard.selected_week.label}
      onClose={onClose}
    >
      <form className="war-progress-form" onSubmit={submit}>
        <label>
          <span>商机</span>
          <select
            value={opportunityId}
            onChange={(event) => selectOpportunity(event.target.value)}
          >
            {dashboard.opportunities
              .filter((opportunity) => opportunity.can_manage)
              .map((opportunity) => (
                <option key={opportunity.id} value={opportunity.id}>
                  {opportunity.name}
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

function graphLayout(projects: DashboardProject[], dims: GraphDims) {
  const centerX = dims.width / 2;
  const centerY = dims.height / 2 - 5;
  const radiusX =
    projects.length > 4 ? dims.width * 0.33 : dims.width * 0.26;
  const radiusY =
    projects.length > 4 ? dims.height * 0.34 : dims.height * 0.27;
  const taskSpreadX = dims.width >= 1600 ? 150 : 112;
  const taskSpreadY = dims.height >= 900 ? 108 : 82;
  const projectNodes: GraphProjectNode[] = projects.map(
    (project, index) => {
      const angle =
        (Math.PI * 2 * index) / Math.max(projects.length, 1) - Math.PI / 2;
      return {
        project,
        x: centerX + Math.cos(angle) * radiusX,
        y: centerY + Math.sin(angle) * radiusY,
      };
    },
  );
  const taskNodes: GraphTaskNode[] = [];
  projectNodes.forEach((node) => {
    node.project.tasks.slice(0, 6).forEach((task, index, tasks) => {
      const angle = (Math.PI * 2 * index) / Math.max(tasks.length, 1);
      taskNodes.push({
        task,
        projectId: node.project.id,
        x: node.x + Math.cos(angle) * taskSpreadX,
        y: node.y + Math.sin(angle) * taskSpreadY,
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

function projectStatusLabel(status: DashboardProject["lifecycle_status"]) {
  return (
    {
      pending: "待确认",
      active: "进行中",
      paused: "已暂停",
      completed: "已完成",
      archived: "已归档",
      rejected: "已驳回",
      merged: "已合并",
    }[status] ?? status
  );
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
  return `${dashboard.selected_week.label} · 解决方案部商机摘要\n\n${dashboard.opportunities
    .map(
      (opportunity) =>
        `【${ATTENTION[opportunity.attention_status].label}】${opportunity.name}（${stageLabel(opportunity.business_stage)} · ${opportunity.progress_percent}%）：${opportunity.work_summary}`,
    )
    .join("\n")}`;
}

function opportunityProjectDraft(
  opportunity: DashboardOpportunity,
): ProjectCreationDraft {
  return {
    opportunity_id: opportunity.id,
    opportunity_revision: opportunity.revision,
    opportunity_code: opportunity.code,
    name: opportunity.name,
    description: [
      opportunity.customer_name ? `客户：${opportunity.customer_name}` : "",
      opportunity.description ?? "",
    ]
      .filter(Boolean)
      .join("\n"),
    owner_id: opportunity.owner_id,
  };
}

function optionalFormValue(value: FormDataEntryValue | null) {
  const text = String(value ?? "").trim();
  return text || null;
}

function workSummary(dashboard: Dashboard) {
  return `${dashboard.selected_week.label} · 解决方案部工作摘要\n\n${dashboard.members
    .map(
      (member) =>
        `${member.display_name}：${
          member.submitted
            ? member.weekly_minutes === null
              ? "已提交，工时不可见"
              : `已提交，${formatHours(member.weekly_minutes)}h`
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
