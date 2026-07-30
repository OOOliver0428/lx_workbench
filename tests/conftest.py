from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import (
    Base,
    PermissionKey,
    ProjectTag,
    User,
    UserPermission,
    UserRole,
)
from app.security import hash_password

TEST_PASSWORD = "Mvp-Test-Password-2026"


@pytest.fixture
def api(tmp_path: Path) -> Iterator[dict[str, Any]]:
    database_path = tmp_path / "test.db"
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
        allowed_hosts_csv="testserver",
        cors_origins_csv="http://127.0.0.1:5173,http://localhost:5173",
        cookie_secure=False,
        llm_config_secret="test-only-llm-config-secret-at-least-32-characters",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        Base.metadata.create_all(app.state.engine)
        with app.state.session_factory.begin() as db:
            users = {
                "member": User(
                    login_name="member",
                    display_name="成员甲",
                    password_hash=hash_password(TEST_PASSWORD),
                    role=UserRole.MEMBER.value,
                    avatar_key="flat-01",
                    must_change_password=False,
                ),
                "member2": User(
                    login_name="member2",
                    display_name="成员乙",
                    password_hash=hash_password(TEST_PASSWORD),
                    role=UserRole.MEMBER.value,
                    avatar_key="flat-02",
                    must_change_password=False,
                ),
                "leader": User(
                    login_name="leader",
                    display_name="团队负责人",
                    password_hash=hash_password(TEST_PASSWORD),
                    role=UserRole.TEAM_LEADER.value,
                    avatar_key="line-01",
                    must_change_password=False,
                ),
                "admin": User(
                    login_name="admin",
                    display_name="系统管理员",
                    password_hash=hash_password(TEST_PASSWORD),
                    role=UserRole.SYSTEM_ADMIN.value,
                    avatar_key="line-02",
                    must_change_password=False,
                ),
                "super_admin": User(
                    login_name="super_admin",
                    display_name="隐藏超级管理员",
                    password_hash=hash_password(TEST_PASSWORD),
                    role=UserRole.SUPER_ADMIN.value,
                    avatar_key="paper-01",
                    must_change_password=False,
                ),
            }
            db.add_all(users.values())
            db.flush()
            member_permissions = {
                PermissionKey.DASHBOARD_OPPORTUNITY_VIEW,
                PermissionKey.DASHBOARD_WORK_VIEW,
                PermissionKey.PROJECTS_MANAGE,
                PermissionKey.TASKS_MANAGE,
                PermissionKey.WORK_RECORDS_MANAGE,
                PermissionKey.WEEKLY_REPORTS_MANAGE,
                PermissionKey.AI_USE,
            }
            leader_permissions = {
                *member_permissions,
                PermissionKey.DASHBOARD_OVERVIEW_VIEW,
                PermissionKey.DASHBOARD_TEAM_SUMMARY,
            }
            admin_permissions = set(PermissionKey)
            permission_sets = {
                "member": member_permissions,
                "member2": member_permissions,
                "leader": leader_permissions,
                "admin": admin_permissions,
            }
            db.add_all(
                UserPermission(
                    user_id=users[user_key].id,
                    permission_key=permission.value,
                    granted_by=users["super_admin"].id,
                )
                for user_key, permissions in permission_sets.items()
                for permission in permissions
            )
            tags = {
                "opportunity": ProjectTag(
                    name="商机",
                    normalized_name="商机",
                    description="拓展新客户或向老客户销售新产品",
                    sort_order=10,
                ),
                "change": ProjectTag(
                    name="改造",
                    normalized_name="改造",
                    description="已有产品功能需求或测评改造",
                    sort_order=20,
                ),
            }
            db.add_all(tags.values())
            db.flush()
            user_ids = {key: value.id for key, value in users.items()}
            tag_ids = {key: value.id for key, value in tags.items()}

        yield {
            "client": client,
            "app": app,
            "users": user_ids,
            "tags": tag_ids,
        }


def login(client: TestClient, login_name: str) -> str:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/login",
        json={"login_name": login_name, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]
