from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import login


def test_occupancy_returns_own_blocks_and_excludes_other_users(
    api: dict,
) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")

    created = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": csrf},
        json={
            "work_date": "2026-08-14",
            "content": "上午方案评审",
            "minutes": 60,
            "time_blocks": [{"start": 540, "end": 600}],
        },
    )
    assert created.status_code == 201, created.text
    record_id = created.json()["id"]

    other_csrf = login(client, "member2")
    other = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": other_csrf},
        json={
            "work_date": "2026-08-14",
            "content": "他人同日记录",
            "minutes": 60,
            "time_blocks": [{"start": 600, "end": 660}],
        },
    )
    assert other.status_code == 201, other.text

    login(client, "member")
    response = client.get(
        "/api/v1/work-records/occupancy",
        params={"date": "2026-08-14"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["date"] == "2026-08-14"
    assert payload["time_blocks"] == [{"start": 540, "end": 600}]

    excluded = client.get(
        "/api/v1/work-records/occupancy",
        params={"date": "2026-08-14", "exclude_record_id": record_id},
    )
    assert excluded.status_code == 200, excluded.text
    assert excluded.json()["time_blocks"] == []


def test_occupancy_ignores_soft_deleted_records(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")

    created = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": csrf},
        json={
            "work_date": "2026-08-15",
            "content": "将删除的记录",
            "minutes": 30,
            "time_blocks": [{"start": 480, "end": 510}],
        },
    )
    assert created.status_code == 201, created.text
    record = created.json()

    deleted = client.request(
        "DELETE",
        f"/api/v1/work-records/{record['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": record["revision"], "reason": "测试删除"},
    )
    assert deleted.status_code == 204, deleted.text

    response = client.get(
        "/api/v1/work-records/occupancy",
        params={"date": "2026-08-15"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["time_blocks"] == []
