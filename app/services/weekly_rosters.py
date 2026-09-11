from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.models import User, UserRole, WeeklyReport, WeeklyRoster, utc_now


def current_week() -> date:
    today = datetime.now(timezone(timedelta(hours=8))).date()
    return today - timedelta(days=today.weekday())


def capture_current_roster(db: Session) -> WeeklyRoster:
    """Save this week's observed roster; never synthesize missing past weeks.

    Called on management reads/submissions and after successful organization mutations.
    First formal submissions override later transfers within the same week.
    """
    db.flush()
    week = current_week()
    reports = {
        report.author_id: report
        for report in db.scalars(
            select(WeeklyReport).where(
                WeeklyReport.week_start == week,
                WeeklyReport.submitted_at.is_not(None),
                WeeklyReport.submitted_content.is_not(None),
            )
        )
    }
    users = db.scalars(select(User).where(User.role != UserRole.SUPER_ADMIN.value)).all()
    members = []
    for user in users:
        report = reports.get(user.id)
        if not user.is_active and report is None:
            continue
        known = report is not None and (
            report.department_snapshot_known or report.department_id is not None
        )
        members.append(
            {
                "user_id": user.id,
                "department_id": report.department_id if known else user.primary_department_id,
                "leader_id": user.leader_id,
                "role": user.role,
            }
        )
    # SQLite UPSERT avoids a unique-key race on the first access of a new week.
    db.execute(
        insert(WeeklyRoster)
        .values(
            week_start=week,
            members=members,
            captured_at=utc_now(),
        )
        .on_conflict_do_update(
            index_elements=["week_start"],
            set_={"members": members, "captured_at": utc_now()},
        )
    )
    roster = db.get(WeeklyRoster, week, populate_existing=True)
    assert roster is not None
    return roster
