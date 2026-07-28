from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_csrf
from app.models import User
from app.schemas import (
    WeeklyReportCurrentOut,
    WeeklyReportDraftUpdate,
    WeeklyReportInboxOut,
    WeeklyReportOut,
    WeeklyReportSubmit,
)
from app.services import weekly_reports as report_service

router = APIRouter(prefix="/weekly-reports", tags=["weekly-reports"])


@router.get("/current", response_model=WeeklyReportCurrentOut)
def get_current_weekly_report(
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WeeklyReportCurrentOut:
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
    db: Session = Depends(get_db),
) -> list[WeeklyReportOut]:
    return [
        report_service.report_out(report)
        for report in report_service.list_own_reports(db, actor)
    ]


@router.get("/inbox", response_model=list[WeeklyReportInboxOut])
def list_weekly_report_inbox(
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WeeklyReportInboxOut]:
    return report_service.list_inbox(db, actor)


@router.post("/current/generate", response_model=WeeklyReportOut)
def generate_current_weekly_report(
    request: Request,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> WeeklyReportOut:
    report = report_service.generate_current_report(
        db,
        request.app.state.settings,
        actor,
    )
    return report_service.report_out(report)


@router.patch("/{report_id}/draft", response_model=WeeklyReportOut)
def save_weekly_report_draft(
    report_id: str,
    payload: WeeklyReportDraftUpdate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> WeeklyReportOut:
    report = report_service.get_report(db, report_id)
    return report_service.report_out(
        report_service.save_draft(db, report, payload, actor)
    )


@router.post("/{report_id}/submit", response_model=WeeklyReportOut)
def submit_weekly_report(
    report_id: str,
    payload: WeeklyReportSubmit,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> WeeklyReportOut:
    report = report_service.get_report(db, report_id)
    return report_service.report_out(
        report_service.submit_report(db, report, payload, actor)
    )
