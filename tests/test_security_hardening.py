from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm.exc import StaleDataError

from app.api.routes import auth as auth_route
from app.dependencies import get_db
from app.errors import AppError
from app.models import AuditEvent, User, UserRole
from app.security import hash_password, verify_password_for_login
from app.throttle import LoginCapacityExceeded, LoginThrottle
from tests.conftest import TEST_PASSWORD, login


def test_login_throttle_caps_rotating_identifiers_with_a_global_budget() -> None:
    throttle = LoginThrottle(
        max_verifications=3,
        max_source_verifications=3,
        max_concurrent=1,
    )

    for index in range(3):
        with throttle.verification_slot(f"198.51.100.{index + 1}"):
            pass

    with (
        pytest.raises(LoginCapacityExceeded),
        throttle.verification_slot("203.0.113.99"),
    ):
        pass


def test_login_failure_state_is_bounded_and_audits_are_sampled() -> None:
    throttle = LoginThrottle(max_keys=128, audit_limit=2)

    decisions = [
        throttle.record_login_failure("proxy", f"unknown-{index}")
        for index in range(256)
    ]

    assert sum(decision.should_audit for decision in decisions) == 2
    assert throttle.tracked_key_count <= 128


def test_wrong_passwords_do_not_lock_out_the_correct_password(api: dict) -> None:
    client: TestClient = api["client"]

    for _ in range(5):
        response = client.post(
            "/api/v1/auth/login",
            json={"login_name": "member", "password": "wrong-password"},
        )
        assert response.status_code == 401

    recovered = client.post(
        "/api/v1/auth/login",
        json={"login_name": "member", "password": TEST_PASSWORD},
    )
    assert recovered.status_code == 200, recovered.text


def test_unknown_and_inactive_users_use_dummy_password_verification(
    api: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client: TestClient = api["client"]
    with api["app"].state.session_factory.begin() as db:
        db.add(
            User(
                login_name="inactive-account",
                display_name="停用账号",
                password_hash=hash_password(TEST_PASSWORD),
                role=UserRole.MEMBER.value,
                is_active=False,
                must_change_password=False,
            )
        )

    calls: list[str | None] = []

    def tracked_verify(password_hash: str | None, password: str) -> bool:
        calls.append(password_hash)
        return verify_password_for_login(password_hash, password)

    monkeypatch.setattr(auth_route, "verify_password_for_login", tracked_verify)

    unknown = client.post(
        "/api/v1/auth/login",
        json={"login_name": "missing-account", "password": "wrong-password"},
    )
    inactive = client.post(
        "/api/v1/auth/login",
        json={"login_name": "inactive-account", "password": "wrong-password"},
    )

    assert unknown.status_code == 401
    assert inactive.status_code == 401
    assert calls == [None, None]


def test_failed_login_audit_survives_request_rollback(api: dict) -> None:
    client: TestClient = api["client"]

    response = client.post(
        "/api/v1/auth/login",
        headers={"X-Request-ID": "failed-login-audit-test"},
        json={"login_name": "member", "password": "wrong-password"},
    )

    assert response.status_code == 401
    with api["app"].state.session_factory() as db:
        event = db.scalar(
            select(AuditEvent).where(
                AuditEvent.request_id == "failed-login-audit-test",
                AuditEvent.action == "auth.login",
                AuditEvent.result == "failure",
            )
        )
        assert event is not None
        assert event.actor_id == api["users"]["member"]
        assert event.entity_id == api["users"]["member"]


def test_non_super_admin_audit_view_keeps_system_events(api: dict) -> None:
    client: TestClient = api["client"]
    with api["app"].state.session_factory.begin() as db:
        event = AuditEvent(
            actor_id=None,
            action="system.test",
            entity_type="system",
            entity_id=None,
            result="success",
        )
        db.add(event)
        db.flush()
        event_id = event.id

    login(client, "admin")
    response = client.get("/api/v1/audit-events")

    assert response.status_code == 200, response.text
    assert event_id in {item["id"] for item in response.json()}


def test_user_directory_requires_business_access_and_protects_inactive_users(
    api: dict,
) -> None:
    client: TestClient = api["client"]
    with api["app"].state.session_factory.begin() as db:
        db.add_all(
            [
                User(
                    login_name="no-directory-access",
                    display_name="无目录权限",
                    password_hash=hash_password(TEST_PASSWORD),
                    role=UserRole.MEMBER.value,
                    must_change_password=False,
                ),
                User(
                    login_name="inactive-directory-user",
                    display_name="目录停用用户",
                    password_hash=hash_password(TEST_PASSWORD),
                    role=UserRole.MEMBER.value,
                    is_active=False,
                    must_change_password=False,
                ),
            ]
        )

    login(client, "no-directory-access")
    assert client.get("/api/v1/users").status_code == 403
    assert client.get("/api/v1/users?include_inactive=true").status_code == 403
    assert client.get("/api/v1/users/candidates").status_code == 403

    login(client, "member")
    assert client.get("/api/v1/users").status_code == 403
    visible = client.get("/api/v1/users/candidates")
    assert visible.status_code == 200, visible.text
    assert "inactive-directory-user" not in {
        user["display_name"] for user in visible.json()
    }
    assert all(
        set(user)
        == {"id", "display_name", "avatar_key", "primary_department_id"}
        for user in visible.json()
    )
    sensitive_fields = {
        "login_name",
        "is_active",
        "must_change_password",
        "revision",
        "role",
        "leader_id",
    }
    assert all(not sensitive_fields.intersection(user) for user in visible.json())

    login(client, "admin")
    admin_visible = client.get("/api/v1/users?include_inactive=true")
    assert admin_visible.status_code == 200, admin_visible.text
    assert "inactive-directory-user" in {
        user["login_name"] for user in admin_visible.json()
    }


def test_get_db_converts_stale_write_to_revision_conflict() -> None:
    class StaleCommitSession:
        def __init__(self) -> None:
            self.info: dict[str, str | None] = {}
            self.rolled_back = False
            self.closed = False

        def commit(self) -> None:
            raise StaleDataError("concurrent update")

        def rollback(self) -> None:
            self.rolled_back = True

        def close(self) -> None:
            self.closed = True

    db = StaleCommitSession()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(session_factory=lambda: db)),
        state=SimpleNamespace(request_id="stale-write-test"),
        client=SimpleNamespace(host="testclient"),
    )
    dependency = get_db(request)
    assert next(dependency) is db

    with pytest.raises(AppError) as captured:
        next(dependency)

    assert captured.value.status_code == 409
    assert captured.value.code == "REVISION_CONFLICT"
    assert db.rolled_back
    assert db.closed
