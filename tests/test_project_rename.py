from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import login


def _create_project(client: TestClient, csrf: str, name: str) -> dict:
    response = client.post(
        "/api/v1/projects",
        headers={"X-CSRF-Token": csrf},
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_owner_without_projects_edit_can_rename(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    project = _create_project(client, csrf, "负责人可改名项目")

    # member 默认有 projects.create（含 edit 扩展）——显式去掉 edit 后仅靠 owner 身份
    with api["app"].state.session_factory.begin() as db:
        from app.models import PermissionKey, UserPermission

        db.query(UserPermission).filter(
            UserPermission.user_id == api["users"]["member"],
            UserPermission.permission_key == PermissionKey.PROJECTS_EDIT.value,
        ).delete()
        db.query(UserPermission).filter(
            UserPermission.user_id == api["users"]["member"],
            UserPermission.permission_key == PermissionKey.PROJECTS_CREATE.value,
        ).delete()

    login(client, "member")
    renamed = client.patch(
        f"/api/v1/projects/{project['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": project["revision"], "name": "负责人改名后的项目"},
    )
    # csrf after re-login
    if renamed.status_code == 403:
        csrf = login(client, "member")
        renamed = client.patch(
            f"/api/v1/projects/{project['id']}",
            headers={"X-CSRF-Token": csrf},
            json={"revision": project["revision"], "name": "负责人改名后的项目"},
        )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "负责人改名后的项目"

    # 无 edit 时不能改其它字段
    blocked = client.patch(
        f"/api/v1/projects/{project['id']}",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": renamed.json()["revision"],
            "description": "负责人不应能无 edit 改描述",
        },
    )
    assert blocked.status_code == 403, blocked.text


def test_non_owner_without_edit_cannot_rename(api: dict) -> None:
    client: TestClient = api["client"]
    owner_csrf = login(client, "member")
    project = _create_project(client, owner_csrf, "仅负责人可改名")
    with api["app"].state.session_factory.begin() as db:
        from app.models import PermissionKey, UserPermission

        db.query(UserPermission).filter(
            UserPermission.user_id == api["users"]["member2"],
            UserPermission.permission_key.in_(
                [
                    PermissionKey.PROJECTS_EDIT.value,
                    PermissionKey.PROJECTS_CREATE.value,
                ]
            ),
        ).delete()

    other_csrf = login(client, "member2")
    blocked = client.patch(
        f"/api/v1/projects/{project['id']}",
        headers={"X-CSRF-Token": other_csrf},
        json={"revision": project["revision"], "name": "越权改名"},
    )
    assert blocked.status_code == 403, blocked.text
