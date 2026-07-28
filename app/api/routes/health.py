from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dependencies import get_db

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict[str, bool]:
    return {"ok": True}


@router.get("/health/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, object]:
    db.execute(text("SELECT 1"))
    return {"ok": True, "database": "ready"}
