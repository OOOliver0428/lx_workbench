from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import AuthSession, User
from app.services import ai as ai_service
from tests.conftest import TEST_PASSWORD, login
from tests.test_ai import ProviderClient


def assign(api: dict, account: str, permissions: list[str], actor: str = "super_admin") -> None:
    client = api["client"]
    csrf = login(client, actor)
    user_id = api["users"][account]
    current = client.get(f"/api/v1/users/{user_id}/permissions").json()
    response = client.put(
        f"/api/v1/users/{user_id}/permissions",
        headers={"X-CSRF-Token": csrf},
        json={"revision": current["revision"], "permissions": permissions},
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("account", ["member", "leader"])
def test_department_two_levels_and_revocation(api: dict, account: str) -> None:
    client = api["client"]
    assign(api, account, ["departments.view"], actor="admin")
    csrf = login(client, account)
    headers = {"X-CSRF-Token": csrf}
    assert client.get("/api/v1/departments").status_code == 200
    people = client.get("/api/v1/departments/personnel")
    assert people.status_code == 200, people.text
    assert api["users"]["member"] in {row["id"] for row in people.json()}
    assert api["users"]["super_admin"] not in {row["id"] for row in people.json()}
    assert all("revision" not in row and "must_change_password" not in row for row in people.json())
    assert client.get("/api/v1/users?include_inactive=true").status_code == 403
    assert (
        client.post("/api/v1/departments", headers=headers, json={"name": "只读禁止"}).status_code
        == 403
    )

    assign(api, account, ["departments.manage"], actor="admin")
    csrf = login(client, account)
    headers = {"X-CSRF-Token": csrf}
    assert "departments.view" in client.get("/api/v1/auth/me").json()["permissions"]
    created = client.post("/api/v1/departments", headers=headers, json={"name": "权限验证部门"})
    assert created.status_code == 201, created.text
    department = created.json()
    path = f"/api/v1/departments/{department['id']}"
    updated = client.patch(
        path,
        headers=headers,
        json={"revision": department["revision"], "name": "已修改", "is_active": False},
    )
    assert updated.status_code == 200, updated.text
    assert (
        client.request(
            "DELETE", path, headers=headers, json={"revision": updated.json()["revision"]}
        ).status_code
        == 204
    )

    assign(api, account, [])
    login(client, account)
    assert client.get("/api/v1/departments").status_code == 403
    assert client.get("/api/v1/departments/personnel").status_code == 403


@pytest.mark.parametrize("account", ["member", "leader"])
@pytest.mark.parametrize("department_access", [False, True])
def test_delegated_tags_and_ai_without_user_management(
    api: dict, monkeypatch, account: str, department_access: bool
) -> None:
    client = api["client"]
    permissions = ["settings.tags.manage", "settings.ai.manage"]
    if department_access:
        permissions.append("departments.view")
    assign(api, account, permissions)
    csrf = login(client, account)
    headers = {"X-CSRF-Token": csrf}
    assert client.get("/api/v1/users").status_code == 403
    if department_access:
        assert client.get("/api/v1/departments/personnel").status_code == 200
    assert client.get("/api/v1/project-tags?include_inactive=true").status_code == 200
    tag = client.post("/api/v1/project-tags", headers=headers, json={"name": "授权标签"})
    assert tag.status_code == 201, tag.text
    changed = client.patch(
        f"/api/v1/project-tags/{tag.json()['id']}",
        headers=headers,
        json={"revision": tag.json()["revision"], "name": "更新标签"},
    )
    assert changed.status_code == 200, changed.text
    assert client.get("/api/v1/ai/providers").status_code == 200
    assert client.get("/api/v1/ai/configuration").status_code == 200
    monkeypatch.setattr(ai_service.httpx, "Client", ProviderClient)
    payload = {
        "provider": "deepseek",
        "access_mode": "standard",
        "model": "deepseek-v4-flash",
        "api_key": "test-settings-secret",
    }
    tested = client.post("/api/v1/ai/configuration/test", headers=headers, json=payload)
    assert tested.status_code == 200, tested.text
    saved = client.put(
        "/api/v1/ai/configuration",
        headers=headers,
        json={
            **payload,
            "verification_token": tested.json()["verification_token"],
            "revision": None,
        },
    )
    assert saved.status_code == 200, saved.text
    assert payload["api_key"] not in saved.text
    assign(api, account, [])
    csrf = login(client, account)
    assert client.get("/api/v1/ai/configuration").status_code == 403
    assert (
        client.post(
            "/api/v1/project-tags", headers={"X-CSRF-Token": csrf}, json={"name": "禁止标签"}
        ).status_code
        == 403
    )


def test_frozen_login_message_requires_correct_password_and_creates_no_session(api: dict) -> None:
    client = api["client"]
    with api["app"].state.session_factory.begin() as db:
        db.get(User, api["users"]["member"]).is_active = False
    for identifier in ["member", "成员甲"]:
        wrong = client.post(
            "/api/v1/auth/login", json={"login_name": identifier, "password": "wrong-password"}
        )
        assert wrong.status_code == 401
        assert wrong.json()["code"] == "INVALID_CREDENTIALS"
        frozen = client.post(
            "/api/v1/auth/login", json={"login_name": identifier, "password": TEST_PASSWORD}
        )
        assert frozen.status_code == 401
        assert frozen.json()["code"] == "ACCOUNT_FROZEN"
        assert frozen.json()["message"] == "该账号已冻结，请联系系统管理员"
        assert "set-cookie" not in frozen.headers
    with api["app"].state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 0
    with api["app"].state.session_factory.begin() as db:
        db.get(User, api["users"]["member"]).is_active = True
    login(client, "member")
