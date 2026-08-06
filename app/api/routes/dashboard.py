from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_csrf
from app.models import User
from app.schemas import (
    DashboardOut,
    TeamWeeklySummaryGenerate,
    TeamWeeklySummaryOut,
)
from app.services import dashboard as dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardOut)
def get_dashboard(
    week_start: date | None = None,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> DashboardOut:
    return dashboard_service.build_dashboard(
        db,
        actor,
        selected_week_start=week_start,
    )


@router.post("/team-summary", response_model=TeamWeeklySummaryOut)
def generate_team_summary(
    week_start: date,
    payload: TeamWeeklySummaryGenerate,
    request: Request,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> TeamWeeklySummaryOut:
    summary = dashboard_service.generate_team_summary(
        db,
        request.app.state.settings,
        payload,
        actor,
        week_start=week_start,
        llm_guard=request.app.state.llm_guard,
    )
    return TeamWeeklySummaryOut.model_validate(summary)
