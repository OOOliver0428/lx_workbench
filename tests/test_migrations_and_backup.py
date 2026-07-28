from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.backup import create_backup
from app.config import get_settings
from app.database import create_database_engine


def upgrade_temp_database(tmp_path: Path, monkeypatch) -> Path:
    database_path = tmp_path / "migrated.db"
    monkeypatch.setenv("MVP_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    return database_path


def test_initial_migration_creates_schema_and_seed_tags(tmp_path: Path, monkeypatch) -> None:
    database_path = upgrade_temp_database(tmp_path, monkeypatch)
    with closing(sqlite3.connect(database_path)) as db:
        tags = db.execute(
            "SELECT name, description FROM project_tags ORDER BY sort_order"
        ).fetchall()
        revision = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        ai_config_table = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_provider_configs'"
        ).fetchone()
        ai_config_columns = {
            item[1] for item in db.execute("PRAGMA table_info(ai_provider_configs)")
        }
        duration_triggers = {
            item[0]
            for item in db.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'trigger' AND name LIKE 'ck_work_records_minutes_%'
                """
                )
            }
        user_columns = {item[1] for item in db.execute("PRAGMA table_info(users)")}
        weekly_report_table = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='weekly_reports'"
        ).fetchone()
    engine = create_database_engine(get_settings())
    with engine.connect() as connection:
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
        journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar_one()
    engine.dispose()
    assert [item[0] for item in tags] == ["商机", "改造"]
    assert tags[0][1]
    assert revision == "a1c7e3f9b2d4"
    assert "leader_id" in user_columns
    assert "avatar_key" in user_columns
    assert weekly_report_table == ("weekly_reports",)
    assert ai_config_table == ("ai_provider_configs",)
    assert "access_mode" in ai_config_columns
    assert duration_triggers == {
        "ck_work_records_minutes_insert",
        "ck_work_records_minutes_update",
    }
    assert foreign_keys == 1
    assert journal_mode == "wal"
    get_settings.cache_clear()


def test_online_backup_is_integrity_checked_and_manifested(tmp_path: Path, monkeypatch) -> None:
    database_path = upgrade_temp_database(tmp_path, monkeypatch)
    with closing(sqlite3.connect(database_path)) as db:
        db.execute(
            """
            INSERT INTO users(
                id, login_name, display_name, password_hash, role,
                is_active, must_change_password, created_at, updated_at, revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "10f240f0-b605-4180-904d-bb57c8b7c5d8",
                "backup-user",
                "备份验证用户",
                "not-a-real-password-hash",
                "member",
                1,
                0,
                "2026-07-27T00:00:00+00:00",
                "2026-07-27T00:00:00+00:00",
                1,
            ),
        )
        db.commit()

    backup_path, manifest_path = create_backup(tmp_path / "offsite")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with closing(sqlite3.connect(backup_path)) as backup:
        integrity = backup.execute("PRAGMA integrity_check").fetchone()[0]
        display_name = backup.execute(
            "SELECT display_name FROM users WHERE login_name='backup-user'"
        ).fetchone()[0]
    assert integrity == "ok"
    assert display_name == "备份验证用户"
    assert manifest["schemaRevision"] == "a1c7e3f9b2d4"
    assert manifest["sha256"]
    assert manifest["sizeBytes"] == backup_path.stat().st_size
    get_settings.cache_clear()
