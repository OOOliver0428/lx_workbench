from datetime import timedelta

from sqlalchemy import delete

from app.models import PermissionKey, UserPermission, WorkRecord, utc_now
from app.schemas import AIChatOut
from app.services import changelog as changelog_service
from app.services.weekly_reports import current_week_bounds
from tests.conftest import login


def test_dashboard_delete_capability_matches_authorization(api):
    client = api["client"]
    csrf = login(client, "member")
    created = client.post(
        "/api/v1/opportunities", headers={"X-CSRF-Token": csrf}, json={"name": "可删除商机"}
    )
    assert created.status_code == 201
    opportunity = created.json()
    url = f"/api/v1/opportunities/{opportunity['id']}"
    assert opportunity["can_delete"] is True
    assert client.get("/api/v1/dashboard").json()["opportunities"][0]["can_delete"] is True

    other_csrf = login(client, "member2")
    assert client.get("/api/v1/dashboard").json()["opportunities"][0]["can_delete"] is False
    assert (
        client.request(
            "DELETE", url, headers={"X-CSRF-Token": other_csrf}, json={"revision": 1}
        ).status_code
        == 403
    )

    csrf = login(client, "member")
    with api["app"].state.session_factory.begin() as db:
        db.execute(
            delete(UserPermission).where(
                UserPermission.user_id == api["users"]["member"],
                UserPermission.permission_key.in_(
                    [
                        PermissionKey.DASHBOARD_OPPORTUNITY_PROGRESS.value,
                        PermissionKey.DASHBOARD_OPPORTUNITY_CREATE.value,
                    ]
                ),
            )
        )
    assert client.get("/api/v1/dashboard").json()["opportunities"][0]["can_delete"] is False
    assert (
        client.request(
            "DELETE", url, headers={"X-CSRF-Token": csrf}, json={"revision": 1}
        ).status_code
        == 403
    )

    admin_csrf = login(client, "super_admin")
    assert (
        client.request(
            "DELETE", url, headers={"X-CSRF-Token": admin_csrf}, json={"revision": 99}
        ).status_code
        == 409
    )
    assert (
        client.request(
            "DELETE", url, headers={"X-CSRF-Token": admin_csrf}, json={"revision": 1}
        ).status_code
        == 204
    )
    assert client.get(url).status_code == 404
    assert client.get("/api/v1/dashboard").json()["opportunities"] == []


def test_linked_opportunity_cannot_be_deleted(api):
    client = api["client"]
    csrf = login(client, "member")
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/v1/opportunities", headers=headers, json={"name": "关联商机"}
    ).json()
    url = f"/api/v1/opportunities/{created['id']}"
    week, _ = current_week_bounds()
    progress = client.post(
        url + "/progress",
        headers=headers,
        json={
            "revision": created["revision"],
            "week_start": week.isoformat(),
            "business_stage": "solution_exchange",
            "attention_status": "steady",
            "progress_percent": 20,
            "summary": "方案交流",
        },
    )
    assert progress.status_code == 201, progress.text
    opportunity = client.get(url).json()
    converted = client.post(
        url + "/convert-to-project",
        headers=headers,
        json={"revision": opportunity["revision"], "project": {"name": "关联项目"}},
    )
    assert converted.status_code == 201, converted.text
    opportunity = client.get(url).json()
    assert opportunity["can_delete"] is False
    assert client.get("/api/v1/dashboard").json()["opportunities"][0]["can_delete"] is False
    denied = client.request(
        "DELETE", url, headers=headers, json={"revision": opportunity["revision"]}
    )
    assert denied.status_code == 409
    assert denied.json()["code"] == "OPPORTUNITY_LINKED_PROJECT"


def test_create_draft_preserves_newer_and_submitted_content(api):
    client = api["client"]
    csrf = login(client, "member2")
    headers = {"X-CSRF-Token": csrf}
    url = "/api/v1/weekly-reports/current/draft"
    first = client.post(url, headers=headers, json={"content": "B 页面草稿"})
    assert first.status_code == 200
    report = first.json()
    stale = client.post(url, headers=headers, json={"content": "A 页面旧预览"})
    assert stale.status_code == 409
    assert stale.json()["code"] == "WEEKLY_REPORT_ALREADY_EXISTS"
    assert client.get("/api/v1/weekly-reports/current").json()["report"] == report
    patch_url = f"/api/v1/weekly-reports/{report['id']}/draft"
    updated = client.patch(
        patch_url, headers=headers, json={"revision": report["revision"], "content": "最新编辑"}
    )
    assert updated.status_code == 200
    assert (
        client.patch(
            patch_url, headers=headers, json={"revision": report["revision"], "content": "过期编辑"}
        ).status_code
        == 409
    )
    submitted = client.post(
        f"/api/v1/weekly-reports/{report['id']}/submit",
        headers=headers,
        json={"revision": updated.json()["revision"], "overwrite_confirmed": False},
    )
    assert submitted.status_code == 200, submitted.text
    assert client.post(url, headers=headers, json={"content": "旧预览"}).status_code == 409
    current = client.get("/api/v1/weekly-reports/current").json()["report"]
    assert current["content"] == current["submitted_content"] == "最新编辑"


def test_ai_preview_does_not_write_report(api, monkeypatch):
    captured = []

    def complete(_db, _settings, *, messages, max_tokens):
        captured.extend(messages)
        return AIChatOut(answer="生成预览", model="test", usage={"total_tokens": 10})

    monkeypatch.setattr("app.services.weekly_reports.ai_service.complete", complete)
    client = api["client"]
    csrf = login(client, "member")
    response = client.post(
        "/api/v1/weekly-reports/current/generate-preview",
        headers={"X-CSRF-Token": csrf},
        json={"guidance": "请突出风险"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["content"] == "生成预览"
    assert "请突出风险" in captured[-1]["content"]
    assert client.get("/api/v1/weekly-reports/current").json()["report"] is None


def test_week_pagination_and_totals_preserve_filters_and_privacy(api):
    client = api["client"]
    csrf = login(client, "member")
    start, _ = current_week_bounds()
    user_id = api["users"]["member"]
    project = client.post(
        "/api/v1/projects", headers={"X-CSRF-Token": csrf}, json={"name": "分页项目"}
    ).json()
    with api["app"].state.session_factory.begin() as db:

        def record(author=user_id, day=start, **values):
            return WorkRecord(
                author_id=author,
                last_edited_by=author,
                work_date=day,
                minutes=30,
                content="分页记录",
                **values,
            )

        db.add_all(record(project_id=project["id"]) for _ in range(51))
        db.add_all(
            [
                record(day=start - timedelta(days=1), project_id=project["id"]),
                record(project_id=project["id"], deleted_at=utc_now()),
                record(author=api["users"]["member2"], project_id=project["id"]),
                record(),
            ]
        )
    params = {"current_week_only": "true", "limit": 50, "project_id": project["id"]}
    first = client.get("/api/v1/work-records", params=params)
    assert first.status_code == 200
    rows = first.json()
    assert len(rows) == 50
    last = rows[-1]
    cursor = {**params, "before_date": last["work_date"], "before_id": last["id"]}
    second = client.get("/api/v1/work-records", params=cursor).json()
    assert len(second) == 1
    assert len({row["id"] for row in rows + second}) == 51
    assert all(row["work_date"] == start.isoformat() for row in rows + second)
    for query in (params, cursor):
        assert client.get("/api/v1/work-records/stats", params=query).json() == {
            "count": 51,
            "total_minutes": 1530,
            "week_minutes": 1530,
        }
    assert client.get(
        "/api/v1/work-records/stats", params={"project_id": project["id"]}
    ).json() == {
        "count": 52,
        "total_minutes": 1560,
        "week_minutes": 1530,
    }
    assert client.get("/api/v1/work-records/stats", params={"unassigned_only": True}).json() == {
        "count": 1,
        "total_minutes": 30,
        "week_minutes": 30,
    }
    assert client.get("/api/v1/work-records/stats", params={"project_id": "missing"}).json() == {
        "count": 0,
        "total_minutes": 0,
        "week_minutes": 0,
    }
    # A forged author filter must not disclose someone else's totals.
    assert (
        client.get(
            "/api/v1/work-records/stats",
            params={
                **params,
                "author_id": api["users"]["member2"],
            },
        ).json()["count"]
        == 51
    )


def test_changelog_reorders_by_shanghai_day_before_limiting(api):
    client = api["client"]
    csrf = login(client, "super_admin")
    headers = {"X-CSRF-Token": csrf}
    entries = []
    for timestamp in (
        "2026-09-22T07:00:00+08:00",
        "2026-09-22T01:00:00Z",
        "2026-09-22T23:59:00+08:00",
        "2026-09-23T00:01:00+08:00",
    ):
        response = client.post(
            "/api/v1/changelog",
            headers=headers,
            json={
                "occurred_at": timestamp,
                "category": "feature",
                "title": timestamp,
                "body": "测试",
            },
        )
        assert response.status_code == 201
        entries.append(response.json())
    assert [entry["sort_order"] for entry in entries] == [1, 2, 3, 1]
    ordered_ids = [entry["id"] for entry in entries[:3]]
    response = client.post(
        "/api/v1/changelog/reorder", headers=headers, json={"entry_ids": ordered_ids}
    )
    assert response.status_code == 200, response.text
    expected = [entries[3]["id"], *ordered_ids]
    assert [row["id"] for row in response.json()] == expected
    assert [row["id"] for row in client.get("/api/v1/changelog").json()] == expected
    with api["app"].state.session_factory() as db:
        assert [
            row.id for row in changelog_service.list_changelog_entries(db, limit=2)
        ] == expected[:2]
    # Same UTC date, different Shanghai dates: must reject.
    cross_day = client.post(
        "/api/v1/changelog/reorder",
        headers=headers,
        json={"entry_ids": [entries[2]["id"], entries[3]["id"]]},
    )
    assert cross_day.status_code == 422
    duplicate = client.post(
        "/api/v1/changelog/reorder",
        headers=headers,
        json={"entry_ids": [ordered_ids[0], ordered_ids[0]]},
    )
    assert duplicate.status_code == 422
    csrf = login(client, "member")
    assert (
        client.post(
            "/api/v1/changelog/reorder",
            headers={"X-CSRF-Token": csrf},
            json={"entry_ids": ordered_ids},
        ).status_code
        == 403
    )
