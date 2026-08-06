from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_csrf
from app.models import PermissionKey, User
from app.schemas import (
    TeamWeeklySummaryOut,
    WeeklyReportCurrentOut,
    WeeklyReportDraftUpdate,
    WeeklyReportOut,
    WeeklyReportSubmit,
)
from app.services import permissions as permission_service
from app.services import weekly_reports as report_service

router = APIRouter(prefix="/weekly-reports", tags=["weekly-reports"])


@router.get("/current", response_model=WeeklyReportCurrentOut)
def get_current_weekly_report(
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> WeeklyReportCurrentOut:
    permission_service.assert_permission(db, actor, PermissionKey.WEEKLY_REPORTS_VIEW)
    week_start, week_end = report_service.current_week_bounds()
    report = report_service.get_current_report(db, actor)
    return WeeklyReportCurrentOut(
        week_start=week_start,
        week_end=week_end,
        report=report_service.report_out(report) if report else None,
    )


@router.get("", response_model=list[WeeklyReportOut])
def list_own_weekly_reports(
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> list[WeeklyReportOut]:
    permission_service.assert_permission(db, actor, PermissionKey.WEEKLY_REPORTS_VIEW)
    return [
        report_service.report_out(report)
        for report in report_service.list_own_reports(db, actor)
    ]


@router.get("/team-summaries", response_model=list[TeamWeeklySummaryOut])
def list_team_weekly_summaries(
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> list[TeamWeeklySummaryOut]:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.DASHBOARD_TEAM_SUMMARY,
        "当前账号没有查看团队周报的权限",
    )
    return [
        TeamWeeklySummaryOut.model_validate(summary)
        for summary in report_service.list_own_team_summaries(db, actor)
    ]


@router.post("/current/generate", response_model=WeeklyReportOut)
def generate_current_weekly_report(
    request: Request,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> WeeklyReportOut:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.WEEKLY_REPORTS_MANAGE,
    )
    week_start, _week_end = report_service.current_week_bounds()
    with request.app.state.llm_guard.generation(
        user_id=actor.id,
        purpose="weekly_report",
        max_tokens=4096,
        idempotency_key=f"weekly-report:{actor.id}:{week_start.isoformat()}",
    ) as lease:
        report = report_service.generate_current_report(
            db,
            request.app.state.settings,
            actor,
        )
        lease.record_usage(report.generation_usage)
    return report_service.report_out(report)


@router.patch("/{report_id}/draft", response_model=WeeklyReportOut)
def save_weekly_report_draft(
    report_id: str,
    payload: WeeklyReportDraftUpdate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> WeeklyReportOut:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.WEEKLY_REPORTS_MANAGE,
    )
    report = report_service.get_report(db, report_id)
    return report_service.report_out(
        report_service.save_draft(db, report, payload, actor)
    )


@router.post("/{report_id}/submit", response_model=WeeklyReportOut)
def submit_weekly_report(
    report_id: str,
    payload: WeeklyReportSubmit,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> WeeklyReportOut:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.WEEKLY_REPORTS_MANAGE,
    )
    report = report_service.get_report(db, report_id)
    return report_service.report_out(
        report_service.submit_report(db, report, payload, actor)
    )
