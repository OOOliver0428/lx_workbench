from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.schemas import AIChatOut
from app.services import weekly_reports as report_service
from tests.conftest import login


def test_admin_assigns_direct_leader_with_role_and_revision_guards(api: dict) -> None:
    client: TestClient = api["client"]
    member_id = api["users"]["member"]
    leader_id = api["users"]["leader"]

    member_csrf = login(client, "member")
    forbidden = client.patch(
        f"/api/v1/users/{member_id}/leader",
        headers={"X-CSRF-Token": member_csrf},
        json={"revision": 1, "leader_id": leader_id},
    )
    assert forbidden.status_code == 403

    admin_csrf = login(client, "admin")
    users = client.get("/api/v1/users").json()
    member = next(item for item in users if item["id"] == member_id)
    invalid = client.patch(
        f"/api/v1/users/{member_id}/leader",
        headers={"X-CSRF-Token": admin_csrf},
        json={"revision": member["revision"], "leader_id": api["users"]["member2"]},
    )
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "DIRECT_LEADER_INVALID"

    updated = client.patch(
        f"/api/v1/users/{member_id}/leader",
        headers={"X-CSRF-Token": admin_csrf},
        json={"revision": member["revision"], "leader_id": leader_id},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["leader_id"] == leader_id
    assert updated.json()["revision"] == member["revision"] + 1

    stale = client.patch(
        f"/api/v1/users/{member_id}/leader",
        headers={"X-CSRF-Token": admin_csrf},
        json={"revision": member["revision"], "leader_id": None},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "REVISION_CONFLICT"

    refreshed_users = client.get("/api/v1/users").json()
    refreshed_member = next(
        item for item in refreshed_users if item["id"] == api["users"]["member"]
    )
    system_admin_leader = client.patch(
        f"/api/v1/users/{refreshed_member['id']}/leader",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "revision": refreshed_member["revision"],
            "leader_id": api["users"]["admin"],
        },
    )
    assert system_admin_leader.status_code == 200, system_admin_leader.text
    assert system_admin_leader.json()["leader_id"] == api["users"]["admin"]

    member2 = next(
        item for item in refreshed_users if item["id"] == api["users"]["member2"]
    )
    promoted = client.patch(
        f"/api/v1/users/{member2['id']}",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "revision": member2["revision"],
            "display_name": member2["display_name"],
            "role": "team_leader",
            "leader_id": api["users"]["leader"],
        },
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["role"] == "team_leader"

    admin = next(
        item for item in refreshed_users if item["id"] == api["users"]["admin"]
    )
    self_role_change = client.patch(
        f"/api/v1/users/{admin['id']}",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "revision": admin["revision"],
            "display_name": admin["display_name"],
            "role": "member",
            "leader_id": None,
        },
    )
    assert self_role_change.status_code == 400
    assert self_role_change.json()["code"] == "SELF_ROLE_CHANGE_FORBIDDEN"

    leader = next(
        item for item in refreshed_users if item["id"] == api["users"]["leader"]
    )
    demotion_with_reports = client.patch(
        f"/api/v1/users/{leader['id']}",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "revision": leader["revision"],
            "display_name": leader["display_name"],
            "role": "member",
            "leader_id": None,
        },
    )
    assert demotion_with_reports.status_code == 409
    assert demotion_with_reports.json()["code"] == "LEADER_HAS_DIRECT_REPORTS"


def test_weekly_report_scope_draft_submission_and_leader_visibility(
    api: dict,
    monkeypatch,
) -> None:
    client: TestClient = api["client"]
    captured: dict[str, Any] = {}

    def fake_complete(
        _db,
        _settings,
        *,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> AIChatOut:
        captured["messages"] = messages
        captured["max_tokens"] = max_tokens
        return AIChatOut(
            answer="# 本周周报\n\n项目甲取得进展。",
            model="test-model",
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        )

    monkeypatch.setattr(report_service.ai_service, "complete", fake_complete)
    week_start, _week_end = report_service.current_week_bounds()
    csrf = login(client, "member")
    project_a = client.post(
        "/api/v1/projects",
        headers={"X-CSRF-Token": csrf},
        json={"name": "周报范围项目甲"},
    ).json()
    project_b_response = client.post(
        "/api/v1/projects",
        headers={"X-CSRF-Token": csrf},
        json={"name": "完全无关的远景规划"},
    )
    assert project_b_response.status_code == 201, project_b_response.text
    project_b = project_b_response.json()
    record = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": csrf},
        json={
            "work_date": week_start.isoformat(),
            "content": "完成项目甲需求确认",
            "minutes": 90,
            "project_id": project_a["id"],
        },
    )
    assert record.status_code == 201, record.text

    generated = client.post(
        "/api/v1/weekly-reports/current/generate",
        headers={"X-CSRF-Token": csrf},
    )
    assert generated.status_code == 200, generated.text
    report = generated.json()
    assert report["submitted_content"] is None
    assert report["content"].startswith("# 本周周报")
    assert captured["max_tokens"] == 4096
    generated_context = "\n".join(
        item["content"] for item in captured["messages"] if item["role"] == "system"
    )
    assert project_a["name"] in generated_context
    assert project_b["name"] not in generated_context

    missing_leader = client.post(
        f"/api/v1/weekly-reports/{report['id']}/submit",
        headers={"X-CSRF-Token": csrf},
        json={"revision": report["revision"], "overwrite_confirmed": False},
    )
    assert missing_leader.status_code == 400
    assert missing_leader.json()["code"] == "DIRECT_LEADER_REQUIRED"

    admin_csrf = login(client, "admin")
    member = next(
        item
        for item in client.get("/api/v1/users").json()
        if item["id"] == api["users"]["member"]
    )
    assigned = client.patch(
        f"/api/v1/users/{member['id']}/leader",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "revision": member["revision"],
            "leader_id": api["users"]["admin"],
        },
    )
    assert assigned.status_code == 200, assigned.text

    csrf = login(client, "member")
    current = client.get("/api/v1/weekly-reports/current").json()["report"]
    first_submit = client.post(
        f"/api/v1/weekly-reports/{current['id']}/submit",
        headers={"X-CSRF-Token": csrf},
        json={"revision": current["revision"], "overwrite_confirmed": False},
    )
    assert first_submit.status_code == 200, first_submit.text
    submitted = first_submit.json()
    assert submitted["submission_version"] == 1

    admin_csrf = login(client, "admin")
    assert admin_csrf
    inbox = client.get("/api/v1/weekly-reports/inbox")
    assert inbox.status_code == 200
    assert inbox.json()[0]["content"] == submitted["content"]

    csrf = login(client, "member")
    edited_text = "# 本周周报\n\n人工编辑后的正式内容。"
    saved = client.patch(
        f"/api/v1/weekly-reports/{submitted['id']}/draft",
        headers={"X-CSRF-Token": csrf},
        json={"revision": submitted["revision"], "content": edited_text},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["has_unsubmitted_changes"] is True

    login(client, "admin")
    assert client.get("/api/v1/weekly-reports/inbox").json()[0]["content"] != edited_text

    csrf = login(client, "member")
    confirmation_required = client.post(
        f"/api/v1/weekly-reports/{submitted['id']}/submit",
        headers={"X-CSRF-Token": csrf},
        json={"revision": saved.json()["revision"], "overwrite_confirmed": False},
    )
    assert confirmation_required.status_code == 409
    assert (
        confirmation_required.json()["code"]
        == "WEEKLY_REPORT_OVERWRITE_CONFIRMATION_REQUIRED"
    )
    overwritten = client.post(
        f"/api/v1/weekly-reports/{submitted['id']}/submit",
        headers={"X-CSRF-Token": csrf},
        json={"revision": saved.json()["revision"], "overwrite_confirmed": True},
    )
    assert overwritten.status_code == 200, overwritten.text
    assert overwritten.json()["submission_version"] == 2

    login(client, "admin")
    assert client.get("/api/v1/weekly-reports/inbox").json()[0]["content"] == edited_text

    login(client, "leader")
    assert client.get("/api/v1/weekly-reports/inbox").json() == []

    login(client, "super_admin")
    super_inbox = client.get("/api/v1/weekly-reports/inbox")
    assert super_inbox.status_code == 200
    assert super_inbox.json()[0]["content"] == edited_text
