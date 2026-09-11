from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import TEST_PASSWORD, login


def _user_row(client: TestClient, user_id: str) -> dict:
    listed = client.get("/api/v1/users?include_inactive=true").json()
    return next(item for item in listed if item["id"] == user_id)


def test_admin_can_freeze_and_unfreeze_user(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "admin")
    target = api["users"]["member"]
    row = _user_row(client, target)
    frozen = client.patch(
        f"/api/v1/users/{target}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": row["revision"], "is_active": False},
    )
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["is_active"] is False

    blocked = client.post(
        "/api/v1/auth/login",
        json={"login_name": "member", "password": TEST_PASSWORD},
    )
    assert blocked.status_code == 401, blocked.text

    csrf = login(client, "admin")
    row = _user_row(client, target)
    restored = client.patch(
        f"/api/v1/users/{target}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": row["revision"], "is_active": True},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["is_active"] is True

    ok = client.post(
        "/api/v1/auth/login",
        json={"login_name": "member", "password": TEST_PASSWORD},
    )
    assert ok.status_code == 200, ok.text


def test_freeze_member_without_reports_and_block_leader_freeze(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "admin")
    # leader 仍有在职直属 member2 → 不可冻结
    leader_id = api["users"]["leader"]
    row = _user_row(client, leader_id)
    blocked = client.patch(
        f"/api/v1/users/{leader_id}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": row["revision"], "is_active": False},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "LEADER_HAS_DIRECT_REPORTS"

    member2 = api["users"]["member2"]
    row = _user_row(client, member2)
    response = client.patch(
        f"/api/v1/users/{member2}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": row["revision"], "is_active": False},
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
