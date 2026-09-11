from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import login


def test_release_marker_lifecycle_and_category_conversion(api: dict) -> None:
    client = api["client"]
    csrf = login(client, "super_admin")
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/v1/changelog", headers=headers, json={"category": "release", "title": " 0.3.1 "}
    )
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["title"] == "v0.3.1"
    assert entry["body"] == ""
    assert entry["occurred_at"]
    url = f"/api/v1/changelog/{entry['id']}"
    changed = client.patch(url, headers=headers, json={"revision": 1, "title": "v0.4.0-beta.1"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["occurred_at"] == entry["occurred_at"]
    assert changed.json()["title"] == "v0.4.0-beta.1"
    invalid = client.patch(
        url, headers=headers, json={"revision": 2, "category": "feature", "title": "新功能"}
    )
    assert invalid.status_code == 400
    ordinary = client.patch(
        url,
        headers=headers,
        json={"revision": 2, "category": "feature", "title": "新功能", "body": "说明内容"},
    )
    assert ordinary.status_code == 200, ordinary.text
    marker = client.patch(
        url, headers=headers, json={"revision": 3, "category": "release", "title": "0.4.0"}
    )
    assert marker.status_code == 200, marker.text
    assert marker.json()["body"] == ""
    assert client.get("/api/v1/changelog").json()[0]["category"] == "release"
    assert client.delete(url, headers=headers, params={"revision": 4}).status_code == 204


@pytest.mark.parametrize("title", ["not a version", "0.3.1 trailing", " "])
def test_invalid_release_version_is_rejected(api: dict, title: str) -> None:
    client = api["client"]
    csrf = login(client, "super_admin")
    response = client.post(
        "/api/v1/changelog",
        headers={"X-CSRF-Token": csrf},
        json={"category": "release", "title": title},
    )
    assert response.status_code in {400, 422}
    assert client.get("/api/v1/changelog").json() == []


@pytest.mark.parametrize("login_name", ["member", "admin"])
def test_release_marker_remains_super_admin_only(api: dict, login_name: str) -> None:
    client = api["client"]
    csrf = login(client, login_name)
    response = client.post(
        "/api/v1/changelog",
        headers={"X-CSRF-Token": csrf},
        json={"category": "release", "title": "0.3.1"},
    )
    assert response.status_code == 403


def test_ordinary_changelog_still_requires_body(api: dict) -> None:
    client = api["client"]
    csrf = login(client, "super_admin")
    response = client.post(
        "/api/v1/changelog",
        headers={"X-CSRF-Token": csrf},
        json={"category": "feature", "title": "新功能"},
    )
    assert response.status_code == 400


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
