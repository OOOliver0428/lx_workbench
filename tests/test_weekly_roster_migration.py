import sqlite3
from contextlib import closing
from datetime import date, timedelta

from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from alembic import command
from app.models import Department, TeamWeeklySummary, User, WeeklyReport, utc_now
from tests.test_migrations_and_backup import upgrade_temp_database


def test_roster_migration_preserves_legacy_content_without_inventing_departments(
    tmp_path, monkeypatch
):
    path = upgrade_temp_database(tmp_path, monkeypatch)
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    week = date(2026, 8, 31)
    with Session(engine) as db:
        user = User(
            login_name="migration-review",
            display_name="Migration review",
            password_hash="test-only",
            role="team_leader",
        )
        other = User(
            login_name="migration-other",
            display_name="Other",
            password_hash="test-only",
            role="member",
        )
        db.add_all([user, other])
        db.flush()
        dept = Department(name="Old dept", normalized_name="old dept", created_by=user.id)
        db.add(dept)
        db.flush()
        for author, department in [(user.id, dept.id), (other.id, None)]:
            db.add(
                WeeklyReport(
                    author_id=author,
                    week_start=week,
                    week_end=week + timedelta(days=6),
                    content="preserved",
                    submitted_content="preserved",
                    submitted_at=utc_now(),
                    department_id=department,
                )
            )
        db.add(
            TeamWeeklySummary(
                week_start=week,
                week_end=week + timedelta(days=6),
                generated_by=user.id,
                content="old summary",
                submitted_count=2,
                expected_count=2,
                generation_model="test",
                scope_key="all_led",
            )
        )
        db.commit()
    engine.dispose()
    config = Config("alembic.ini")
    command.downgrade(config, "d2e3f4a5b6c7")
    command.upgrade(config, "head")
    with closing(sqlite3.connect(path)) as db:
        rows = db.execute(
            "SELECT department_id, department_snapshot_known, submitted_content FROM weekly_reports"
        ).fetchall()
        assert len(rows) == 2
        assert all(
            known == (department is not None) and content == "preserved"
            for department, known, content in rows
        )
        assert db.execute("SELECT count(*) FROM weekly_rosters").fetchone()[0] == 0
        assert db.execute("SELECT content,scope_key FROM team_weekly_summaries").fetchone() == (
            "old summary",
            "legacy",
        )
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
