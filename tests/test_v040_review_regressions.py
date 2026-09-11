from datetime import timedelta

from app.models import Department, TeamWeeklySummary, User, WeeklyReport, WeeklyRoster, utc_now
from app.schemas import AIChatOut
from app.services import dashboard as dashboard_service
from app.services.dashboard import normalize_week_start
from tests.conftest import login


def setup_departments(api):
    with api["app"].state.session_factory.begin() as db:
        first = Department(
            name="Review A",
            normalized_name="review a",
            leader_id=api["users"]["leader"],
            created_by=api["users"]["admin"],
        )
        second = Department(
            name="Review B",
            normalized_name="review b",
            leader_id=api["users"]["leader"],
            created_by=api["users"]["admin"],
        )
        db.add_all([first, second])
        db.flush()
        db.get(User, api["users"]["member"]).primary_department_id = first.id
        db.get(User, api["users"]["member2"]).primary_department_id = second.id
        return first.id, second.id


def test_department_does_not_reuse_all_departments_summary(api):
    first, _second = setup_departments(api)
    week = normalize_week_start()
    with api["app"].state.session_factory.begin() as db:
        db.add(
            TeamWeeklySummary(
                week_start=week,
                week_end=week + timedelta(days=6),
                content="SUMMARY CONTAINING BOTH DEPARTMENTS",
                generated_by=api["users"]["leader"],
                submitted_count=2,
                expected_count=2,
                generation_model="review",
                scope_type="all_led",
                scope_key="all_led",
            )
        )
    login(api["client"], "leader")
    response = api["client"].get(
        "/api/v1/dashboard",
        params={
            "scope_type": "department",
            "department_id": first,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["latest_team_summary"] is None


def test_historical_report_stays_with_snapshot_department(api):
    first, second = setup_departments(api)
    week = normalize_week_start() - timedelta(weeks=1)
    member_id = api["users"]["member"]
    with api["app"].state.session_factory.begin() as db:
        db.add(
            WeeklyReport(
                author_id=member_id,
                week_start=week,
                week_end=week + timedelta(days=6),
                content="A department work",
                submitted_content="A department work",
                submitted_at=utc_now(),
                submitted_to_id=api["users"]["leader"],
                department_id=first,
                submission_version=1,
            )
        )
        db.get(User, member_id).primary_department_id = second
    login(api["client"], "leader")
    response = api["client"].get(
        "/api/v1/dashboard",
        params={
            "week_start": week.isoformat(),
            "scope_type": "department",
            "department_id": first,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["metrics"]["submitted_count"] == 1
    assert response.json()["metrics"]["member_count_known"] is False


def test_first_submission_department_survives_transfer_and_resubmit(api):
    first, second = setup_departments(api)
    week = normalize_week_start()
    uid = api["users"]["member"]
    with api["app"].state.session_factory.begin() as db:
        db.get(User, uid).leader_id = api["users"]["leader"]
        report = WeeklyReport(
            author_id=uid,
            week_start=week,
            week_end=week + timedelta(days=6),
            content="First submission",
        )
        db.add(report)
        db.flush()
        rid = report.id
    client = api["client"]
    csrf = login(client, "member")
    result = client.post(
        f"/api/v1/weekly-reports/{rid}/submit", headers={"X-CSRF-Token": csrf}, json={"revision": 1}
    )
    assert result.status_code == 200, result.text
    revision = result.json()["revision"]
    with api["app"].state.session_factory.begin() as db:
        db.get(User, uid).primary_department_id = second
    result = client.post(
        f"/api/v1/weekly-reports/{rid}/submit",
        headers={"X-CSRF-Token": csrf},
        json={"revision": revision, "overwrite_confirmed": True},
    )
    assert result.status_code == 200, result.text
    with api["app"].state.session_factory() as db:
        assert db.get(WeeklyReport, rid).department_id == first
        assert db.get(WeeklyReport, rid).department_snapshot_known is True
        roster = db.get(WeeklyRoster, week)
        assert next(e for e in roster.members if e["user_id"] == uid)["department_id"] == first
    login(client, "leader")
    for dept, expected in [(first, 1), (second, 0)]:
        result = client.get(
            "/api/v1/dashboard",
            params={
                "scope_type": "department",
                "department_id": dept,
            },
        )
        assert result.status_code == 200, result.text
        assert result.json()["metrics"]["submitted_count"] == expected


def test_historical_roster_preserves_missing_members_and_summary_scope(api, monkeypatch):
    first, second = setup_departments(api)
    week = normalize_week_start() - timedelta(weeks=1)
    members = [api["users"]["member"], api["users"]["member2"]]
    with api["app"].state.session_factory.begin() as db:
        db.add(
            WeeklyRoster(
                week_start=week,
                members=[
                    {"user_id": uid, "department_id": first, "leader_id": api["users"]["leader"]}
                    for uid in members
                ],
            )
        )
        db.add(
            WeeklyReport(
                author_id=members[0],
                week_start=week,
                week_end=week + timedelta(days=6),
                content="PRIVATE DRAFT",
                submitted_content="A FORMAL",
                submitted_at=utc_now(),
                department_id=first,
                department_snapshot_known=True,
            )
        )
        for uid in members:
            db.get(User, uid).primary_department_id = second
    captured = []

    def complete(*args, **kwargs):
        captured.extend(kwargs["messages"])
        return AIChatOut(answer="A summary", model="test", usage={})

    monkeypatch.setattr(dashboard_service.ai_service, "complete", complete)
    client = api["client"]
    csrf = login(client, "leader")
    params = {"week_start": week.isoformat(), "scope_type": "department", "department_id": first}
    data = client.get("/api/v1/dashboard", params=params).json()
    assert data["metrics"]["member_count"] == 2
    assert data["metrics"]["member_count_known"] is True
    assert data["metrics"]["submitted_count"] == 1
    assert {m["department_id"] for m in data["members"]} == {first}
    result = client.post(
        "/api/v1/dashboard/team-summary",
        params={"week_start": week.isoformat()},
        headers={"X-CSRF-Token": csrf},
        json={"scope_type": "department", "department_id": first, "force": True},
    )
    assert result.status_code == 200, result.text
    assert result.json()["expected_count"] == 2
    assert result.json()["expected_count_known"] is True
    assert "A FORMAL" in str(captured)
    assert "PRIVATE DRAFT" not in str(captured)
    params["department_id"] = second
    assert client.get("/api/v1/dashboard", params=params).json()["latest_team_summary"] is None


def test_legacy_unknown_department_is_not_guessed(api):
    first, _ = setup_departments(api)
    week = normalize_week_start() - timedelta(weeks=1)
    with api["app"].state.session_factory.begin() as db:
        db.add(
            WeeklyReport(
                author_id=api["users"]["member"],
                week_start=week,
                week_end=week + timedelta(days=6),
                content="Legacy",
                submitted_content="Legacy",
                submitted_at=utc_now(),
            )
        )
    csrf = login(api["client"], "leader")
    params = {"week_start": week.isoformat(), "scope_type": "department", "department_id": first}
    result = api["client"].get("/api/v1/dashboard", params=params)
    assert result.json()["metrics"]["submitted_count"] == 0
    assert result.json()["metrics"]["member_count_known"] is False
    result = api["client"].post(
        "/api/v1/dashboard/team-summary",
        params={"week_start": week.isoformat()},
        headers={"X-CSRF-Token": csrf},
        json={"scope_type": "department", "department_id": first},
    )
    assert result.status_code == 409
    assert result.json()["code"] == "HISTORICAL_ROSTER_UNKNOWN"


def test_next_week_uses_new_department_without_rewriting_old_roster(api, monkeypatch):
    from app.services import weekly_rosters

    first, second = setup_departments(api)
    week = normalize_week_start()
    uid = api["users"]["member"]
    with api["app"].state.session_factory.begin() as db:
        weekly_rosters.capture_current_roster(db)
        before = list(db.get(WeeklyRoster, week).members)
        db.get(User, uid).primary_department_id = second
        monkeypatch.setattr(weekly_rosters, "current_week", lambda: week + timedelta(weeks=1))
        new = weekly_rosters.capture_current_roster(db)
        assert next(e for e in new.members if e["user_id"] == uid)["department_id"] == second
        assert db.get(WeeklyRoster, week).members == before
        assert next(e for e in before if e["user_id"] == uid)["department_id"] == first


def test_unknown_historical_denominator_is_explicit_in_generated_summary(api, monkeypatch):
    first, _ = setup_departments(api)
    week = normalize_week_start() - timedelta(weeks=1)
    with api["app"].state.session_factory.begin() as db:
        db.add(
            WeeklyReport(
                author_id=api["users"]["member"],
                week_start=week,
                week_end=week + timedelta(days=6),
                content="draft",
                submitted_content="formal",
                submitted_at=utc_now(),
                department_id=first,
            )
        )
    captured = []

    def complete(*args, **kwargs):
        captured.extend(kwargs["messages"])
        return AIChatOut(answer="Historical summary", model="test", usage={})

    monkeypatch.setattr(dashboard_service.ai_service, "complete", complete)
    csrf = login(api["client"], "leader")
    result = api["client"].post(
        "/api/v1/dashboard/team-summary",
        params={"week_start": str(week)},
        headers={"X-CSRF-Token": csrf},
        json={"scope_type": "department", "department_id": first, "force": True},
    )
    assert result.status_code == 200, result.text
    assert result.json()["expected_count_known"] is False
    assert result.json()["submitted_count"] == 1
    assert "禁止计算提交率或声称全员提交" in str(captured)
