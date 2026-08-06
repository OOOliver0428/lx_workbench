from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.backup import create_backup, prune_old_backups
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
        user_indexes = {
            item[1]: bool(item[2]) for item in db.execute("PRAGMA index_list(users)")
        }
        weekly_report_table = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='weekly_reports'"
        ).fetchone()
        dashboard_tables = {
            item[0]
            for item in db.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name IN (
                    'project_progress',
                    'task_relations',
                    'team_weekly_summaries',
                    'opportunities',
                    'opportunity_members',
                    'opportunity_progress'
                  )
                """
            )
        }
        permission_table = db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='user_permissions'"
        ).fetchone()
        task_relation_foreign_keys = {
            item[3]: (item[2], item[4])
            for item in db.execute("PRAGMA foreign_key_list(task_relations)")
        }
    engine = create_database_engine(get_settings())
    with engine.connect() as connection:
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
        journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar_one()
    engine.dispose()
    assert [item[0] for item in tags] == ["商机", "改造"]
    assert tags[0][1]
    assert revision == "b3f8d2a6c901"
    assert "leader_id" in user_columns
    assert "avatar_key" in user_columns
    assert "display_name_key" in user_columns
    assert user_indexes["uq_users_display_name_key"] is True
    assert weekly_report_table == ("weekly_reports",)
    assert dashboard_tables == {
        "project_progress",
        "task_relations",
        "team_weekly_summaries",
        "opportunities",
        "opportunity_members",
        "opportunity_progress",
    }
    assert permission_table == ("user_permissions",)
    assert task_relation_foreign_keys["deleted_by"] == ("users", "id")
    assert ai_config_table == ("ai_provider_configs",)
    assert "access_mode" in ai_config_columns
    assert duration_triggers == {
        "ck_work_records_minutes_insert",
        "ck_work_records_minutes_update",
    }
    assert foreign_keys == 1
    assert journal_mode == "wal"
    get_settings.cache_clear()


def test_team_summary_migration_keeps_latest_duplicate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "duplicate-summaries.db"
    monkeypatch.setenv("MVP_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "e5b9c7d1a304")

    with closing(sqlite3.connect(database_path)) as db:
        db.execute(
            """
            INSERT INTO users(
                id, login_name, display_name, display_name_key, password_hash, role,
                is_active, must_change_password, created_at, updated_at, revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "11111111-1111-4111-8111-111111111111",
                "summary-owner",
                "周报负责人",
                "周报负责人",
                "not-a-real-password-hash",
                "team_leader",
                1,
                0,
                "2026-08-01T00:00:00+00:00",
                "2026-08-01T00:00:00+00:00",
                1,
            ),
        )
        db.executemany(
            """
            INSERT INTO team_weekly_summaries(
                id, week_start, week_end, content, generated_by, forced,
                submitted_count, expected_count, generation_model,
                generation_usage, created_at, updated_at, revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "22222222-2222-4222-8222-222222222222",
                    "2026-07-27",
                    "2026-08-02",
                    "旧版本",
                    "11111111-1111-4111-8111-111111111111",
                    0,
                    1,
                    1,
                    "test-model",
                    None,
                    "2026-08-01T00:00:00+00:00",
                    "2026-08-01T00:00:00+00:00",
                    1,
                ),
                (
                    "33333333-3333-4333-8333-333333333333",
                    "2026-07-27",
                    "2026-08-02",
                    "最新版本",
                    "11111111-1111-4111-8111-111111111111",
                    0,
                    1,
                    1,
                    "test-model",
                    None,
                    "2026-08-02T00:00:00+00:00",
                    "2026-08-02T00:00:00+00:00",
                    1,
                ),
            ],
        )
        db.commit()

    command.upgrade(config, "head")
    with closing(sqlite3.connect(database_path)) as db:
        summaries = db.execute(
            "SELECT id, content FROM team_weekly_summaries"
        ).fetchall()
        unique_indexes = [
            row[1]
            for row in db.execute("PRAGMA index_list(team_weekly_summaries)")
            if row[2]
        ]
        unique_column_sets = {
            tuple(
                column[2]
                for column in db.execute(
                    f'PRAGMA index_info("{index_name}")'
                )
            )
            for index_name in unique_indexes
        }

    assert summaries == [
        ("33333333-3333-4333-8333-333333333333", "最新版本")
    ]
    assert ("generated_by", "week_start") in unique_column_sets
    get_settings.cache_clear()


def test_populated_previous_revision_upgrades_without_data_loss(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "historic.db"
    monkeypatch.setenv("MVP_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "f7d3a9c2b104")

    with closing(sqlite3.connect(database_path)) as db:
        db.execute(
            """
            INSERT INTO users(
                id, login_name, display_name, password_hash, role,
                is_active, must_change_password, created_at, updated_at, revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "5f86438e-03ef-44b0-b245-2d37d7a62785",
                "historic-user",
                "  历史升级用户  ",
                "not-a-real-password-hash",
                "member",
                1,
                0,
                "2026-07-27T00:00:00+00:00",
                "2026-07-27T00:00:00+00:00",
                1,
            ),
        )
        db.execute(
            """
            INSERT INTO projects(
                id, code, name, normalized_name, status, owner_id, proposed_by,
                created_at, updated_at, revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "df7ca924-5b2d-4ce4-8667-c99000d1083a",
                "HIST-001",
                "历史商机项目",
                "历史商机项目",
                "active",
                "5f86438e-03ef-44b0-b245-2d37d7a62785",
                "5f86438e-03ef-44b0-b245-2d37d7a62785",
                "2026-07-27T00:00:00+00:00",
                "2026-07-27T00:00:00+00:00",
                1,
            ),
        )
        db.executemany(
            """
            INSERT INTO user_permissions(
                id, user_id, permission_key, granted_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "39bfbe54-9954-4453-95b9-874de77d9060",
                    "5f86438e-03ef-44b0-b245-2d37d7a62785",
                    "projects.manage",
                    None,
                    "2026-07-27T00:00:00+00:00",
                    "2026-07-27T00:00:00+00:00",
                ),
                (
                    "55245dd3-6324-40fc-a45f-123aaf249afc",
                    "5f86438e-03ef-44b0-b245-2d37d7a62785",
                    "tasks.manage",
                    None,
                    "2026-07-27T00:00:00+00:00",
                    "2026-07-27T00:00:00+00:00",
                ),
            ],
        )
        db.execute(
            """
            INSERT INTO project_members(
                id, project_id, user_id, role, added_by, joined_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "96842f96-b9c8-42c0-a27d-786558a01ea8",
                "df7ca924-5b2d-4ce4-8667-c99000d1083a",
                "5f86438e-03ef-44b0-b245-2d37d7a62785",
                "owner",
                "5f86438e-03ef-44b0-b245-2d37d7a62785",
                "2026-07-27T00:00:00+00:00",
            ),
        )
        db.execute(
            """
            INSERT INTO project_progress(
                id, project_id, week_start, business_stage, attention_status,
                progress_percent, summary, output_summary, created_by,
                created_at, updated_at, revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ec85d4ec-acde-490e-8954-f395d94d1570",
                "df7ca924-5b2d-4ce4-8667-c99000d1083a",
                "2026-07-27",
                "solution_exchange",
                "focus",
                40,
                "历史方案交流记录",
                "历史方案初稿",
                "5f86438e-03ef-44b0-b245-2d37d7a62785",
                "2026-07-31T08:00:00+00:00",
                "2026-07-31T08:00:00+00:00",
                1,
            ),
        )
        db.commit()

    command.upgrade(config, "head")
    with closing(sqlite3.connect(database_path)) as db:
        revision = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        user = db.execute(
            """
            SELECT login_name, display_name, display_name_key
            FROM users
            WHERE id = '5f86438e-03ef-44b0-b245-2d37d7a62785'
            """
        ).fetchone()
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        migrated_opportunity = db.execute(
            """
            SELECT name, business_stage, attention_status, progress_percent,
                   linked_project_id
            FROM opportunities
            WHERE linked_project_id = 'df7ca924-5b2d-4ce4-8667-c99000d1083a'
            """
        ).fetchone()
        migrated_progress = db.execute(
            """
            SELECT summary, output_summary FROM opportunity_progress
            WHERE opportunity_id = (
                SELECT id FROM opportunities
                WHERE linked_project_id = 'df7ca924-5b2d-4ce4-8667-c99000d1083a'
            )
            """
        ).fetchone()
        migrated_member_count = db.execute(
            """
            SELECT COUNT(*) FROM opportunity_members
            WHERE opportunity_id = (
                SELECT id FROM opportunities
                WHERE linked_project_id = 'df7ca924-5b2d-4ce4-8667-c99000d1083a'
            )
            """
        ).fetchone()[0]
        migrated_permissions = db.execute(
            """
            SELECT permission_key FROM user_permissions
            WHERE user_id = '5f86438e-03ef-44b0-b245-2d37d7a62785'
            ORDER BY permission_key
            """
        ).fetchall()

    assert revision == "b3f8d2a6c901"
    assert user == ("historic-user", "历史升级用户", "历史升级用户")
    assert integrity == "ok"
    assert migrated_opportunity == (
        "历史商机项目",
        "solution_exchange",
        "focus",
        40,
        "df7ca924-5b2d-4ce4-8667-c99000d1083a",
    )
    assert migrated_progress == ("历史方案交流记录", "历史方案初稿")
    assert migrated_member_count == 1
    assert migrated_permissions == [("projects.create",), ("tasks.create",)]
    get_settings.cache_clear()


def test_online_backup_is_integrity_checked_and_manifested(tmp_path: Path, monkeypatch) -> None:
    database_path = upgrade_temp_database(tmp_path, monkeypatch)
    with closing(sqlite3.connect(database_path)) as db:
        db.execute(
            """
            INSERT INTO users(
                id, login_name, display_name, display_name_key, password_hash, role,
                is_active, must_change_password, created_at, updated_at, revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "10f240f0-b605-4180-904d-bb57c8b7c5d8",
                "backup-user",
                "备份验证用户",
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
    assert manifest["schemaRevision"] == "b3f8d2a6c901"
    assert manifest["sha256"]
    assert manifest["sizeBytes"] == backup_path.stat().st_size

    # Exercise the actual restore shape: replace a lost source file with the
    # verified snapshot, then open and read it as the application database.
    database_path.unlink()
    shutil.copy2(backup_path, database_path)
    with closing(sqlite3.connect(database_path)) as restored:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            restored.execute(
                "SELECT display_name FROM users WHERE login_name='backup-user'"
            ).fetchone()[0]
            == display_name
        )
    get_settings.cache_clear()


def test_backup_retention_only_prunes_expired_mvp_snapshots(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    expired_db = backup_dir / "mvp-20260101T000000000000Z.db"
    expired_manifest = backup_dir / f"{expired_db.name}.manifest.json"
    recent_db = backup_dir / "mvp-20261231T000000000000Z.db"
    unrelated = backup_dir / "keep-me.db"
    for path in (expired_db, expired_manifest, recent_db, unrelated):
        path.write_bytes(b"test")
    expired_time = time.time() - 31 * 24 * 60 * 60
    os.utime(expired_db, (expired_time, expired_time))
    os.utime(expired_manifest, (expired_time, expired_time))

    removed = prune_old_backups(backup_dir, retention_days=30)

    assert set(removed) == {expired_db, expired_manifest}
    assert not expired_db.exists()
    assert not expired_manifest.exists()
    assert recent_db.exists()
    assert unrelated.exists()
