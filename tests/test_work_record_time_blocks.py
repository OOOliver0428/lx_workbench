from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import WorkRecord, WorkRecordTimeBlock
from tests.conftest import login


def test_create_time_blocks_recalculates_minutes_and_keeps_legacy_payloads(
    api: dict,
) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")

    created_response = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": csrf},
        json={
            "work_date": "2026-08-14",
            "content": "完成时间块后端联调",
            "minutes": 30,
            "time_blocks": [
                {"start": 840, "end": 930},
                {"start": 540, "end": 630},
            ],
        },
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    assert created["minutes"] == 180
    assert created["time_blocks"] == [
        {"start": 540, "end": 630},
        {"start": 840, "end": 930},
    ]

    legacy_response = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": csrf},
        json={
            "work_date": "2026-08-14",
            "content": "旧客户端仍按汇总工时录入",
            "minutes": 90,
        },
    )
    assert legacy_response.status_code == 201, legacy_response.text
    assert legacy_response.json()["minutes"] == 90
    assert legacy_response.json()["time_blocks"] == []


@pytest.mark.parametrize(
    "time_blocks",
    [
        [{"start": 60, "end": 60}],
        [{"start": -30, "end": 30}],
        [{"start": 1410, "end": 1470}],
        [{"start": 15, "end": 60}],
        [{"start": 60, "end": 120}, {"start": 90, "end": 150}],
        [{"start": 60, "end": 120}, {"start": 120, "end": 180}],
        [{"start": 0, "end": 30} for _ in range(25)],
    ],
)
def test_invalid_time_blocks_return_422(api: dict, time_blocks: list[dict]) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    response = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": csrf},
        json={
            "work_date": "2026-08-14",
            "content": "非法时间块",
            "minutes": 30,
            "time_blocks": time_blocks,
        },
    )
    assert response.status_code == 422, response.text
    assert "时间块" in response.json()["message"]


def test_update_time_blocks_replaces_or_clears_atomically_and_advances_revision(
    api: dict,
) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    created = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": csrf},
        json={
            "work_date": "2026-08-14",
            "content": "更新时间块",
            "minutes": 30,
            "time_blocks": [{"start": 540, "end": 600}],
        },
    ).json()

    content_only_response = client.patch(
        f"/api/v1/work-records/{created['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": created["revision"], "content": "未修改时间块"},
    )
    assert content_only_response.status_code == 200, content_only_response.text
    content_only = content_only_response.json()
    assert content_only["time_blocks"] == [{"start": 540, "end": 600}]

    replaced_response = client.patch(
        f"/api/v1/work-records/{created['id']}",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": content_only["revision"],
            "minutes": 30,
            "time_blocks": [{"start": 600, "end": 720}],
        },
    )
    assert replaced_response.status_code == 200, replaced_response.text
    replaced = replaced_response.json()
    assert replaced["minutes"] == 120
    assert replaced["time_blocks"] == [{"start": 600, "end": 720}]
    assert replaced["revision"] == content_only["revision"] + 1

    stale_response = client.patch(
        f"/api/v1/work-records/{created['id']}",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": content_only["revision"],
            "time_blocks": [{"start": 720, "end": 780}],
        },
    )
    assert stale_response.status_code == 409, stale_response.text
    assert stale_response.json()["code"] == "WORK_RECORD_REVISION_CONFLICT"

    cleared_response = client.patch(
        f"/api/v1/work-records/{created['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": replaced["revision"], "time_blocks": []},
    )
    assert cleared_response.status_code == 200, cleared_response.text
    cleared = cleared_response.json()
    assert cleared["time_blocks"] == []
    assert cleared["minutes"] == 120

    with api["app"].state.session_factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(WorkRecordTimeBlock)
                .where(WorkRecordTimeBlock.record_id == created["id"])
            )
            == 0
        )


def test_soft_delete_retains_time_blocks_and_hard_delete_cascades(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    created = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": csrf},
        json={
            "work_date": "2026-08-14",
            "content": "验证时间块删除语义",
            "minutes": 30,
            "time_blocks": [{"start": 480, "end": 540}],
        },
    ).json()

    deleted_response = client.request(
        "DELETE",
        f"/api/v1/work-records/{created['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": created["revision"]},
    )
    assert deleted_response.status_code == 204, deleted_response.text

    with api["app"].state.session_factory.begin() as db:
        record = db.get(WorkRecord, created["id"])
        assert record and record.deleted_at is not None
        assert [(block.start_minute, block.end_minute) for block in record.time_blocks] == [
            (480, 540)
        ]
        db.delete(record)

    with api["app"].state.session_factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(WorkRecordTimeBlock)
                .where(WorkRecordTimeBlock.record_id == created["id"])
            )
            == 0
        )


def test_quick_create_idempotency_replays_the_same_time_blocks(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    payload = {
        "idempotency_key": "time-block-quick-create-0001",
        "work_date": "2026-08-14",
        "content": "快速录入时间块",
        "minutes": 30,
        "time_blocks": [{"start": 540, "end": 660}],
    }

    created_response = client.post(
        "/api/v1/work-records/quick-create",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    assert created["work_record"]["minutes"] == 120
    assert created["work_record"]["time_blocks"] == [{"start": 540, "end": 660}]

    replayed_response = client.post(
        "/api/v1/work-records/quick-create",
        headers={"X-CSRF-Token": csrf},
        json=deepcopy(payload),
    )
    assert replayed_response.status_code == 200, replayed_response.text
    replayed = replayed_response.json()
    assert replayed["replayed"] is True
    assert replayed["work_record"]["id"] == created["work_record"]["id"]
    assert replayed["work_record"]["time_blocks"] == created["work_record"]["time_blocks"]
