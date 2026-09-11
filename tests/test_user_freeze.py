from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.models import User
from app.security import hash_password
from tests.conftest import TEST_PASSWORD, login


def _user_row(client: TestClient, user_id: str) -> dict:
    listed = client.get("/api/v1/users?include_inactive=true").json()
    return next(item for item in listed if item["id"] == user_id)


@pytest.mark.parametrize("active", [True, False])
def test_freeze_requires_actor_password_without_partial_update(api: dict, active: bool) -> None:
    client = api["client"]
    target = api["users"]["member"]
    target_password = "Target-Only-Password-2026"
    with api["app"].state.session_factory.begin() as db:
        user = db.get(User, target)
        user.is_active = active
        user.password_hash = hash_password(target_password)
    csrf = login(client, "admin")
    row = _user_row(client, target)
    for password in (None, "wrong-password", target_password):
        response = client.patch(
            f"/api/v1/users/{target}",
            headers={"X-CSRF-Token": csrf},
            json={
                "revision": row["revision"],
                "is_active": not active,
                "display_name": "不应保存的名称",
                **({"current_password": password} if password is not None else {}),
            },
        )
        assert response.status_code == 400, response.text
        assert response.json()["code"] == "INVALID_CURRENT_PASSWORD"
        unchanged = _user_row(client, target)
        assert unchanged["is_active"] is active
        assert unchanged["revision"] == row["revision"]
        assert unchanged["display_name"] == row["display_name"]
    response = client.patch(
        f"/api/v1/users/{target}",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": row["revision"],
            "is_active": not active,
            "current_password": TEST_PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is not active
    assert "current_password" not in response.json()


def test_freeze_password_verification_is_rate_limited(api: dict) -> None:
    client = api["client"]
    csrf = login(client, "admin")
    target = api["users"]["member"]
    row = _user_row(client, target)
    api["app"].state.login_throttle.max_verifications = 0
    response = client.patch(
        f"/api/v1/users/{target}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": row["revision"], "is_active": False, "current_password": TEST_PASSWORD},
    )
    assert response.status_code == 429
    assert _user_row(client, target)["is_active"] is True


def test_admin_can_freeze_and_unfreeze_user(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "admin")
    target = api["users"]["member"]
    row = _user_row(client, target)
    frozen = client.patch(
        f"/api/v1/users/{target}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": row["revision"], "is_active": False, "current_password": TEST_PASSWORD},
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
        json={"revision": row["revision"], "is_active": True, "current_password": TEST_PASSWORD},
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
        json={"revision": row["revision"], "is_active": False, "current_password": TEST_PASSWORD},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "LEADER_HAS_DIRECT_REPORTS"

    member2 = api["users"]["member2"]
    row = _user_row(client, member2)
    response = client.patch(
        f"/api/v1/users/{member2}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": row["revision"], "is_active": False, "current_password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
