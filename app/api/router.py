from fastapi import APIRouter

from app.api.routes import (
    ai,
    audit,
    auth,
    dashboard,
    health,
    profile,
    project_tags,
    projects,
    tasks,
    users,
    weekly_reports,
    work_records,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(dashboard.router)
api_router.include_router(profile.router)
api_router.include_router(users.router)
api_router.include_router(project_tags.router)
api_router.include_router(projects.router)
api_router.include_router(tasks.router)
api_router.include_router(work_records.router)
api_router.include_router(weekly_reports.router)
api_router.include_router(audit.router)
api_router.include_router(ai.router)
