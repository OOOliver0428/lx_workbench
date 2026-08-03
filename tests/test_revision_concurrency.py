from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm.exc import StaleDataError

from app.models import Base, Project
from app.services import projects as project_service
from tests.conftest import login


def test_every_revisioned_model_uses_optimistic_database_locking() -> None:
    revisioned_mappers = [
        mapper for mapper in Base.registry.mappers if "revision" in mapper.columns
    ]

    assert revisioned_mappers
    assert all(
        mapper.version_id_col is mapper.columns["revision"]
        for mapper in revisioned_mappers
    )


def test_concurrent_project_update_rejects_the_late_writer(api: dict) -> None:
    factory = api["app"].state.session_factory
    owner_id = api["users"]["member"]

    with factory.begin() as db:
        project = Project(
            code="PRJ-CONCURRENCY",
            name="并发更新验证项目",
            normalized_name="并发更新验证项目",
            owner_id=owner_id,
            proposed_by=owner_id,
            status="active",
        )
        db.add(project)
        db.flush()
        project_id = project.id

    first = factory()
    second = factory()
    try:
        first_copy = first.get(Project, project_id)
        second_copy = second.get(Project, project_id)
        assert first_copy and second_copy
        assert first_copy.revision == second_copy.revision == 1

        first_copy.description = "第一个请求提交的内容"
        first_copy.revision += 1
        first.commit()

        second_copy.description = "较晚请求不应覆盖前一个请求"
        second_copy.revision += 1
        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()
    finally:
        first.close()
        second.close()

    with factory() as db:
        persisted = db.get(Project, project_id)
        assert persisted
        assert persisted.description == "第一个请求提交的内容"
        assert persisted.revision == 2


def test_concurrent_http_update_returns_revision_conflict(
    api: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    created = client.post(
        "/api/v1/projects",
        headers={"X-CSRF-Token": csrf},
        json={"name": "并发 HTTP 提交验证项目"},
    )
    assert created.status_code == 201, created.text
    project = created.json()

    gate = Barrier(2)
    original_record_audit = project_service.record_audit

    def synchronized_record_audit(*args, **kwargs):
        if kwargs.get("action") == "project.update":
            gate.wait(timeout=5)
        return original_record_audit(*args, **kwargs)

    monkeypatch.setattr(
        project_service,
        "record_audit",
        synchronized_record_audit,
    )

    descriptions = ["并发请求一", "并发请求二"]

    def submit(description: str):
        return client.patch(
            f"/api/v1/projects/{project['id']}",
            headers={"X-CSRF-Token": csrf},
            json={
                "revision": project["revision"],
                "description": description,
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, descriptions))

    assert sorted(response.status_code for response in responses) == [200, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["code"] == "REVISION_CONFLICT"
    winner = next(response for response in responses if response.status_code == 200)

    persisted = client.get(f"/api/v1/projects/{project['id']}")
    assert persisted.status_code == 200, persisted.text
    assert persisted.json()["description"] == winner.json()["description"]
    assert persisted.json()["revision"] == project["revision"] + 1
