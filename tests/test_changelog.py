from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import login


def test_member_can_read_but_not_write_changelog(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")

    listed = client.get("/api/v1/changelog")
    assert listed.status_code == 200, listed.text
    assert listed.json() == []

    created = client.post(
        "/api/v1/changelog",
        headers={"X-CSRF-Token": csrf},
        json={
            "occurred_at": "2026-09-11T04:12:00+08:00",
            "category": "improvement",
            "title": "普通用户不应能创建",
            "body": "权限校验",
        },
    )
    assert created.status_code == 403, created.text


def test_super_admin_can_create_update_and_delete_changelog(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "super_admin")

    created = client.post(
        "/api/v1/changelog",
        headers={"X-CSRF-Token": csrf},
        json={
            "occurred_at": "2026-09-11T04:12:00+08:00",
            "category": "improvement",
            "title": "日报、周报和月报，重点更清楚了",
            "body": "日报改为逐条阅读核心事件。",
        },
    )
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["category"] == "improvement"
    assert entry["title"].startswith("日报")
    assert entry["revision"] == 1

    listed = client.get("/api/v1/changelog")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = client.patch(
        f"/api/v1/changelog/{entry['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": entry["revision"], "title": "日报周报阅读优化"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "日报周报阅读优化"
    assert updated.json()["revision"] == 2

    deleted = client.request(
        "DELETE",
        f"/api/v1/changelog/{entry['id']}",
        headers={"X-CSRF-Token": csrf},
        params={"revision": updated.json()["revision"]},
    )
    assert deleted.status_code == 204, deleted.text

    after = client.get("/api/v1/changelog")
    assert after.status_code == 200
    assert after.json() == []


def test_system_admin_cannot_write_changelog(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "admin")
    created = client.post(
        "/api/v1/changelog",
        headers={"X-CSRF-Token": csrf},
        json={
            "occurred_at": "2026-09-11T05:00:00+08:00",
            "category": "fix",
            "title": "系统管理员不可写",
            "body": "仅超管可维护",
        },
    )
    assert created.status_code == 403, created.text
