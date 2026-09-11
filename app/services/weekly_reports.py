from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.config import Settings
from app.domain import can_be_direct_leader
from app.errors import AppError, ConflictError, NotFoundError, PermissionDeniedError
from app.models import TeamWeeklySummary, User, UserRole, WeeklyReport, utc_now
from app.schemas import (
    WeeklyReportDraftUpdate,
    WeeklyReportOut,
    WeeklyReportSubmit,
)
from app.services import ai as ai_service
from app.services.ai_context import build_weekly_report_context

SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")

WEEKLY_REPORT_SYSTEM_PROMPT = """你是团队协作工作台的周报整理助手。
系统会提供当前用户本自然周的工作记录，以及这些记录实际关联的项目和任务。
只能依据这些事实生成周报，不得补写不存在的成果、进度、风险或计划。
项目没有本周工作记录时不会出现在上下文中；不得自行引入其他项目。
将未关联项目的工作记录单独整理，提醒用户后续补充项目关联。
工时按系统提供的小时数汇总，不要虚构或重复计算。
只输出可直接编辑的 Markdown 周报正文，不要输出解释、前言或代码围栏。"""

WEEKLY_REPORT_USER_PROMPT = """请生成本周周报，使用以下结构：
# 本周周报
## 项目进展
按项目分别总结完成事项、推进结果和投入工时。
## 风险与待协调事项
只汇总工作记录中明确存在的风险、阻塞和需要协调的事项；没有则写“暂无明确记录”。
## 下周计划
根据工作记录中的下一步行动整理；没有依据时写“待补充”。
## 未关联项目的工作
仅在存在未关联项目的工作记录时展示，否则省略本节。

文字应简明、面向直属 Leader 审阅，并保留关键事实。"""


def current_week_bounds(today: date | None = None) -> tuple[date, date]:
    local_today = today or datetime.now(SHANGHAI).date()
    week_start = local_today - timedelta(days=local_today.weekday())
    return week_start, week_start + timedelta(days=6)


def report_out(report: WeeklyReport) -> WeeklyReportOut:
    return WeeklyReportOut.model_validate(report)


def get_report(db: Session, report_id: str) -> WeeklyReport:
    report = db.get(WeeklyReport, report_id)
    if not report:
        raise NotFoundError("WEEKLY_REPORT_NOT_FOUND", "周报不存在")
    return report


def get_current_report(db: Session, actor: User) -> WeeklyReport | None:
    week_start, _week_end = current_week_bounds()
    return db.scalar(
        select(WeeklyReport).where(
            WeeklyReport.author_id == actor.id,
            WeeklyReport.week_start == week_start,
        )
    )


def list_own_reports(db: Session, actor: User) -> list[WeeklyReport]:
    return list(
        db.scalars(
            select(WeeklyReport)
            .where(WeeklyReport.author_id == actor.id)
            .order_by(WeeklyReport.week_start.desc())
            .limit(100)
        ).all()
    )


def list_own_team_summaries(
    db: Session,
    actor: User,
) -> list[TeamWeeklySummary]:
    return list(
        db.scalars(
            select(TeamWeeklySummary)
            .where(TeamWeeklySummary.generated_by == actor.id)
            .order_by(
                TeamWeeklySummary.week_start.desc(),
                TeamWeeklySummary.created_at.desc(),
            )
            .limit(100)
        ).all()
    )


def generate_current_report(
    db: Session,
    settings: Settings,
    actor: User,
) -> WeeklyReport:
    week_start, week_end = current_week_bounds()
    context = build_weekly_report_context(db, actor, week_start, week_end)
    result = ai_service.complete(
        db,
        settings,
        messages=[
            {"role": "system", "content": WEEKLY_REPORT_SYSTEM_PROMPT},
            {
                "role": "system",
                "content": f"以下是系统生成的本周业务事实：\n{context}",
            },
            {"role": "user", "content": WEEKLY_REPORT_USER_PROMPT},
        ],
        max_tokens=4096,
    )
    report = db.scalar(
        select(WeeklyReport).where(
            WeeklyReport.author_id == actor.id,
            WeeklyReport.week_start == week_start,
        )
    )
    is_regeneration = report is not None
    if report:
        report.content = result.answer
        report.generated_at = utc_now()
        report.generation_model = result.model
        report.generation_usage = result.usage
        report.revision += 1
        report.updated_at = utc_now()
    else:
        report = WeeklyReport(
            author_id=actor.id,
            week_start=week_start,
            week_end=week_end,
            content=result.answer,
            generated_at=utc_now(),
            generation_model=result.model,
            generation_usage=result.usage,
        )
        db.add(report)
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="weekly_report.regenerate" if is_regeneration else "weekly_report.generate",
        entity_type="weekly_report",
        entity_id=report.id,
        detail={
            "weekStart": week_start.isoformat(),
            "model": result.model,
            "usage": result.usage,
            "hadSubmittedVersion": report.submitted_content is not None,
        },
    )
    return report


def save_draft(
    db: Session,
    report: WeeklyReport,
    payload: WeeklyReportDraftUpdate,
    actor: User,
) -> WeeklyReport:
    if report.author_id != actor.id:
        raise PermissionDeniedError("只能编辑自己的周报草稿")
    _assert_revision(report, payload.revision)
    report.content = payload.content.strip()
    report.revision += 1
    report.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="weekly_report.draft.save",
        entity_type="weekly_report",
        entity_id=report.id,
        detail={
            "weekStart": report.week_start.isoformat(),
            "hadSubmittedVersion": report.submitted_content is not None,
        },
    )
    return report


def submit_report(
    db: Session,
    report: WeeklyReport,
    payload: WeeklyReportSubmit,
    actor: User,
) -> WeeklyReport:
    if report.author_id != actor.id:
        raise PermissionDeniedError("只能提交自己的周报")
    _assert_revision(report, payload.revision)
    if report.submitted_content is not None and not payload.overwrite_confirmed:
        raise ConflictError(
            "WEEKLY_REPORT_OVERWRITE_CONFIRMATION_REQUIRED",
            "本周已有已提交周报，继续提交会覆盖 Leader 当前看到的版本",
            {"submission_version": report.submission_version},
        )
    leader = db.get(User, actor.leader_id) if actor.leader_id else None
    can_self_publish = (
        actor.leader_id is None
        and actor.role
        in {UserRole.TEAM_LEADER.value, UserRole.SYSTEM_ADMIN.value}
    )
    if (not leader or not can_be_direct_leader(leader)) and not can_self_publish:
        raise AppError(
            "DIRECT_LEADER_REQUIRED",
            "尚未配置有效的直属 Leader，请联系系统管理员后再提交",
        )

    was_submitted = report.submitted_content is not None
    report.submitted_content = report.content
    report.submitted_to_id = leader.id if leader else None
    report.department_id = actor.primary_department_id
    report.submitted_at = utc_now()
    report.submission_version += 1
    report.revision += 1
    report.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="weekly_report.resubmit" if was_submitted else "weekly_report.submit",
        entity_type="weekly_report",
        entity_id=report.id,
        detail={
            "weekStart": report.week_start.isoformat(),
            "submittedToId": leader.id if leader else None,
            "selfPublished": leader is None,
            "submissionVersion": report.submission_version,
        },
    )
    return report


def _assert_revision(report: WeeklyReport, expected_revision: int) -> None:
    if report.revision != expected_revision:
        raise ConflictError(
            "REVISION_CONFLICT",
            "周报已在其他窗口更新，请刷新后重试",
            {
                "expected_revision": expected_revision,
                "current_revision": report.revision,
            },
        )
