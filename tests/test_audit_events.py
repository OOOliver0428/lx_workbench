from __future__ import annotations

from fastapi.testclient import TestClient

from app.models import AuditEvent
from tests.conftest import login


def _seed_events(api: dict, events: list[AuditEvent]) -> list[str]:
    with api["app"].state.session_factory.begin() as db:
        db.add_all(events)
        db.flush()
        return [event.id for event in events]


def test_audit_events_accept_limit_up_to_1000(api: dict) -> None:
    client: TestClient = api["client"]
    _seed_events(
        api,
        [
            AuditEvent(
                actor_id=None,
                action="system.test",
                entity_type="system",
                entity_id=None,
                result="success",
            )
            for _ in range(5)
        ],
    )

    login(client, "admin")
    assert client.get("/api/v1/audit-events?limit=1000").status_code == 200
    assert client.get("/api/v1/audit-events?limit=1001").status_code == 422
    assert client.get("/api/v1/audit-events?limit=0").status_code == 422

    truncated = client.get("/api/v1/audit-events?limit=2")
    assert truncated.status_code == 200, truncated.text
    assert len(truncated.json()) == 2


def test_audit_events_include_actor_name(api: dict) -> None:
    client: TestClient = api["client"]
    seeded = _seed_events(
        api,
        [
            AuditEvent(
                actor_id=api["users"]["member"],
                action="task.update",
                entity_type="task",
                entity_id="task-1",
                result="success",
            ),
            AuditEvent(
                actor_id=None,
                action="system.test",
                entity_type="system",
                entity_id=None,
                result="success",
            ),
        ],
    )

    login(client, "admin")
    response = client.get("/api/v1/audit-events?limit=1000")

    assert response.status_code == 200, response.text
    by_id = {item["id"]: item for item in response.json()}
    assert by_id[seeded[0]]["actor_name"] == "成员甲"
    assert by_id[seeded[1]]["actor_id"] is None
    assert by_id[seeded[1]]["actor_name"] is None


def test_non_super_admin_audit_view_keeps_rules_and_actor_names(api: dict) -> None:
    client: TestClient = api["client"]
    _seed_events(
        api,
        [
            AuditEvent(
                actor_id=api["users"]["super_admin"],
                action="user.create",
                entity_type="user",
                entity_id="user-1",
                result="success",
            ),
            AuditEvent(
                actor_id=api["users"]["member"],
                action="work_record.create",
                entity_type="work_record",
                entity_id="record-1",
                result="success",
            ),
            AuditEvent(
                actor_id=api["users"]["member"],
                action="task.update",
                entity_type="task",
                entity_id="task-1",
                result="success",
            ),
        ],
    )

    super_csrf = login(client, "super_admin")
    member = next(
        user
        for user in client.get("/api/v1/users").json()
        if user["id"] == api["users"]["member2"]
    )
    granted = client.put(
        f"/api/v1/users/{member['id']}/permissions",
        headers={"X-CSRF-Token": super_csrf},
        json={
            "revision": member["revision"],
            "permissions": ["settings.audit.view"],
        },
    )
    assert granted.status_code == 200, granted.text

    login(client, "member2")
    response = client.get("/api/v1/audit-events?limit=1000")

    assert response.status_code == 200, response.text
    events = response.json()
    assert events, "expected at least the seeded member task event"
    assert all(
        event["actor_id"] != api["users"]["super_admin"]
        and event["entity_type"] != "work_record"
        for event in events
    )
    member_events = [
        event for event in events if event["actor_id"] == api["users"]["member"]
    ]
    assert member_events
    assert {event["actor_name"] for event in member_events} == {"成员甲"}
