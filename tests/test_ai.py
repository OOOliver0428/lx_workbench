from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.models import (
    AIProviderConfig,
    Department,
    DepartmentWork,
    DepartmentWorkStatus,
    DepartmentWorkVisibility,
    PermissionKey,
    Project,
    ProjectStatus,
    Task,
    TaskPriority,
    TaskStatus,
    User,
    UserPermission,
    WorkRecord,
    utc_now,
)
from app.services import ai as ai_service
from app.services import ai_context as ai_context_module
from app.services.ai_context import build_chat_context, build_weekly_report_context
from tests.conftest import login

UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
WEEKDAY_NAMES = {"周一", "周二", "周三", "周四", "周五", "周六", "周日"}


class FakeResponse:
    status_code = 200
    is_error = False

    def json(self) -> dict[str, Any]:
        return {
            "model": "MiniMax-M2.7",
            "choices": [
                {
                    "message": {
                        "content": "<think>internal reasoning</think>\n\n建议先确认项目负责人。"
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "total_tokens": 30,
            },
        }


class FakeClient:
    def __init__(self, *, timeout: float) -> None:
        assert timeout == 60

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> FakeResponse:
        assert url == "https://api.minimaxi.com/v1/chat/completions"
        assert headers["Authorization"] == "Bearer test-token"
        assert json["model"] == "MiniMax-M2.7"
        return FakeResponse()


def test_ai_status_and_chat_proxy(api: dict, monkeypatch) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")

    status = client.get("/api/v1/ai/status")
    assert status.status_code == 200
    assert status.json()["configured"] is False
    assert "api_key" not in status.text.casefold()

    api["app"].state.settings.minimax_api_key = "test-token"
    monkeypatch.setattr(ai_service.httpx, "Client", FakeClient)
    response = client.post(
        "/api/v1/ai/chat",
        headers={"X-CSRF-Token": csrf},
        json={"prompt": "下一步应该做什么？", "context": "项目刚刚创建。"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "answer": "建议先确认项目负责人。",
        "model": "MiniMax-M2.7",
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "total_tokens": 30,
        },
    }


def test_ai_context_omits_project_and_task_data_without_view_permissions(
    api: dict,
) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    project = client.post(
        "/api/v1/projects",
        headers={"X-CSRF-Token": csrf},
        json={"name": "AI context permission sentinel"},
    )
    assert project.status_code == 201, project.text
    record = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": csrf},
        json={
            "work_date": date.today().isoformat(),
            "content": "permission-filtered record",
            "minutes": 30,
            "project_id": project.json()["id"],
        },
    )
    assert record.status_code == 201, record.text

    project_and_task_permissions = {
        PermissionKey.PROJECTS_VIEW.value,
        PermissionKey.PROJECTS_EDIT.value,
        PermissionKey.PROJECTS_CREATE.value,
        PermissionKey.DEPARTMENTS_VIEW.value,
        PermissionKey.DEPARTMENTS_MANAGE.value,
        PermissionKey.DEPARTMENT_WORKS_VIEW.value,
        PermissionKey.DEPARTMENT_WORKS_EDIT.value,
        PermissionKey.DEPARTMENT_WORKS_CREATE.value,
        PermissionKey.TASKS_VIEW.value,
        PermissionKey.TASKS_EDIT.value,
        PermissionKey.TASKS_CREATE.value,
    }
    with api["app"].state.session_factory.begin() as db:
        db.execute(
            delete(UserPermission).where(
                UserPermission.user_id == api["users"]["member"],
                UserPermission.permission_key.in_(project_and_task_permissions),
            )
        )

    with api["app"].state.session_factory() as db:
        actor = db.get(User, api["users"]["member"])
        assert actor is not None
        chat_context = json.loads(build_chat_context(db, actor))
        weekly_context = json.loads(
            build_weekly_report_context(db, actor, date.today(), date.today())
        )

    for context in (chat_context, weekly_context):
        assert context["projects"] == []
        assert context["department_works"] == []
        assert context["tasks"] == []
        assert context["work_records"]
        assert "project_name" not in context["work_records"][0]
        assert "department_work_name" not in context["work_records"][0]
        assert "task_title" not in context["work_records"][0]


def test_ai_context_includes_only_visible_related_department_work(api: dict) -> None:
    today = date.today()
    with api["app"].state.session_factory.begin() as db:
        actor = db.get(User, api["users"]["member"])
        foreign_owner = db.get(User, api["users"]["member2"])
        creator = db.get(User, api["users"]["super_admin"])
        assert actor is not None
        assert foreign_owner is not None
        assert creator is not None

        local_department = Department(
            name="AI Context Local Department",
            normalized_name="ai context local department",
            leader_id=None,
            created_by=creator.id,
        )
        foreign_department = Department(
            name="AI Context Foreign Department",
            normalized_name="ai context foreign department",
            leader_id=None,
            created_by=creator.id,
        )
        db.add_all([local_department, foreign_department])
        db.flush()
        actor.primary_department_id = local_department.id
        foreign_owner.primary_department_id = foreign_department.id

        local_work = DepartmentWork(
            code="DWK-AI-LOCAL",
            name="Local department work",
            normalized_name="local department work",
            description="Local trusted context",
            department_id=local_department.id,
            owner_id=actor.id,
            status=DepartmentWorkStatus.IN_PROGRESS.value,
            visibility=DepartmentWorkVisibility.DEPARTMENT_ONLY.value,
            created_by=actor.id,
        )
        public_work = DepartmentWork(
            code="DWK-AI-PUBLIC",
            name="Public related department work",
            normalized_name="public related department work",
            description="Public trusted context",
            department_id=foreign_department.id,
            owner_id=foreign_owner.id,
            status=DepartmentWorkStatus.IN_PROGRESS.value,
            visibility=DepartmentWorkVisibility.PUBLIC.value,
            created_by=foreign_owner.id,
        )
        hidden_work = DepartmentWork(
            code="DWK-AI-HIDDEN",
            name="Hidden foreign department work",
            normalized_name="hidden foreign department work",
            description="Must not enter AI context",
            department_id=foreign_department.id,
            owner_id=foreign_owner.id,
            status=DepartmentWorkStatus.IN_PROGRESS.value,
            visibility=DepartmentWorkVisibility.DEPARTMENT_ONLY.value,
            created_by=foreign_owner.id,
        )
        db.add_all([local_work, public_work, hidden_work])
        db.flush()

        local_task = Task(
            project_id=None,
            department_work_id=local_work.id,
            parent_id=None,
            level=0,
            title="Tracked local task",
            owner_id=actor.id,
            created_by=actor.id,
            priority=TaskPriority.P1.value,
            status=TaskStatus.IN_PROGRESS.value,
            progress_enabled=True,
            progress_percent=45,
        )
        public_task = Task(
            project_id=None,
            department_work_id=public_work.id,
            parent_id=None,
            level=0,
            title="Tracked public task",
            owner_id=actor.id,
            created_by=actor.id,
            priority=TaskPriority.P1.value,
            status=TaskStatus.TODO.value,
            progress_enabled=False,
            progress_percent=None,
        )
        hidden_task = Task(
            project_id=None,
            department_work_id=hidden_work.id,
            parent_id=None,
            level=0,
            title="Hidden task",
            owner_id=actor.id,
            created_by=actor.id,
            priority=TaskPriority.P1.value,
            status=TaskStatus.TODO.value,
            progress_enabled=False,
            progress_percent=None,
        )
        db.add_all([local_task, public_task, hidden_task])
        db.flush()
        db.add(
            WorkRecord(
                author_id=actor.id,
                work_date=today,
                content="Weekly department work result",
                minutes=60,
                project_id=None,
                department_work_id=local_work.id,
                task_id=local_task.id,
                last_edited_by=actor.id,
            )
        )
        db.flush()

    with api["app"].state.session_factory() as db:
        actor = db.get(User, api["users"]["member"])
        assert actor is not None
        chat_context = json.loads(build_chat_context(db, actor))
        weekly_context = json.loads(
            build_weekly_report_context(db, actor, today, today)
        )

    assert {row["code"] for row in chat_context["department_works"]} == {
        "DWK-AI-LOCAL",
        "DWK-AI-PUBLIC",
    }
    assert {row["title"] for row in chat_context["tasks"]} == {
        "Tracked local task",
        "Tracked public task",
    }
    local_task_row = next(
        row for row in chat_context["tasks"] if row["title"] == "Tracked local task"
    )
    assert local_task_row["department_work_name"] == "Local department work"
    assert "parent_id" not in local_task_row
    assert local_task_row["level"] == 0
    assert local_task_row["owner_name"] == "成员甲"
    assert local_task_row["mine"] is True
    assert local_task_row["status"] == "处理中"
    assert local_task_row["progress_percent"] == 45
    assert chat_context["work_records"][0]["department_work_name"] == "Local department work"
    assert chat_context["work_records"][0]["task_title"] == "Tracked local task"

    assert [row["code"] for row in weekly_context["department_works"]] == [
        "DWK-AI-LOCAL"
    ]
    assert [row["title"] for row in weekly_context["tasks"]] == [
        "Tracked local task"
    ]
    assert weekly_context["work_records"][0]["department_work_name"] == "Local department work"


def test_ai_context_humanizes_names_labels_and_dates(api: dict) -> None:
    today = date.today()
    with api["app"].state.session_factory.begin() as db:
        actor = db.get(User, api["users"]["member"])
        assert actor is not None
        project = Project(
            code="AI-HUM-001",
            name="人话化验证项目",
            normalized_name="人话化验证项目",
            description="验证上下文中的名称与标签",
            status=ProjectStatus.ACTIVE.value,
            owner_id=actor.id,
            proposed_by=actor.id,
            planned_start_date=today,
            planned_end_date=today,
        )
        db.add(project)
        db.flush()
        db.add(
            Task(
                project_id=project.id,
                level=0,
                title="验证任务",
                owner_id=actor.id,
                created_by=actor.id,
                priority=TaskPriority.P2.value,
                status=TaskStatus.DONE.value,
                completed_at=utc_now(),
                progress_enabled=False,
                progress_percent=None,
            )
        )
        db.flush()
        db.add(
            WorkRecord(
                author_id=actor.id,
                work_date=today,
                content="人话化验证记录",
                minutes=60,
                project_id=project.id,
                last_edited_by=actor.id,
            )
        )
        db.flush()

    with api["app"].state.session_factory() as db:
        actor = db.get(User, api["users"]["member"])
        assert actor is not None
        context_text = build_chat_context(db, actor)
    context = json.loads(context_text)

    assert context["current_user"] == {"display_name": "成员甲"}
    assert context["today"] == today.isoformat()
    assert context["weekday"] in WEEKDAY_NAMES
    assert context["week_start"] <= context["today"] <= context["week_end"]

    project_row = next(
        row for row in context["projects"] if row["code"] == "AI-HUM-001"
    )
    assert project_row["owner_name"] == "成员甲"
    assert project_row["mine"] is True
    assert project_row["status"] == "进行中"
    assert "owner_id" not in project_row
    assert "id" not in project_row

    task_row = next(row for row in context["tasks"] if row["title"] == "验证任务")
    assert task_row["project_name"] == "人话化验证项目"
    assert task_row["owner_name"] == "成员甲"
    assert task_row["mine"] is True
    assert task_row["status"] == "已完成"
    assert task_row["priority"] == "P2"
    assert task_row["updated_at"]
    assert task_row["completed_at"]
    assert "description" not in task_row
    assert "progress_enabled" not in task_row

    record_row = context["work_records"][0]
    assert record_row["project_name"] == "人话化验证项目"
    assert "null" not in context_text
    assert not UUID_PATTERN.search(context_text)


def test_ai_context_marks_truncated_sections(api: dict, monkeypatch) -> None:
    monkeypatch.setattr(ai_context_module, "CONTEXT_TASK_LIMIT", 1)
    with api["app"].state.session_factory.begin() as db:
        actor = db.get(User, api["users"]["member"])
        assert actor is not None
        project = Project(
            code="AI-TRN-001",
            name="截断验证项目",
            normalized_name="截断验证项目",
            status=ProjectStatus.ACTIVE.value,
            owner_id=actor.id,
            proposed_by=actor.id,
        )
        db.add(project)
        db.flush()
        for index in range(2):
            db.add(
                Task(
                    project_id=project.id,
                    level=0,
                    title=f"截断验证任务 {index}",
                    owner_id=actor.id,
                    created_by=actor.id,
                    priority=TaskPriority.P1.value,
                    status=TaskStatus.TODO.value,
                )
            )
        db.flush()

    with api["app"].state.session_factory() as db:
        actor = db.get(User, api["users"]["member"])
        assert actor is not None
        context = json.loads(build_chat_context(db, actor))

    assert context["counts"]["tasks"] == 1
    assert "tasks" in context["truncated_sections"]
    assert "截断" in context["scope"]


class ProviderResponse:
    status_code = 200
    is_error = False

    def __init__(self, model: str, content: str = "连接成功") -> None:
        self.model = model
        self.content = content

    def json(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "choices": [{"message": {"content": self.content}}],
            "usage": {
                "prompt_tokens": 8,
                "completion_tokens": 2,
                "total_tokens": 10,
            },
        }


class ProviderClient:
    calls: list[dict[str, Any]] = []

    def __init__(self, *, timeout: float) -> None:
        assert timeout == 60

    def __enter__(self) -> ProviderClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> ProviderResponse:
        self.calls.append({"url": url, "headers": headers, "json": json})
        content = "建议先确认项目范围。" if len(json["messages"]) > 1 else "连接成功"
        return ProviderResponse(json["model"], content)


class TokenPlanResponse:
    status_code = 200
    is_error = False

    def json(self) -> dict[str, Any]:
        return {
            "model": "MiniMax-M2.7",
            "content": [
                {"type": "thinking", "thinking": "internal reasoning"},
                {"type": "text", "text": "Token Plan 连接正常。"},
            ],
            "usage": {"input_tokens": 12, "output_tokens": 5},
        }


class TokenPlanClient:
    calls: list[dict[str, Any]] = []

    def __init__(self, *, timeout: float) -> None:
        assert timeout == 60

    def __enter__(self) -> TokenPlanClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> TokenPlanResponse:
        self.calls.append({"url": url, "headers": headers, "json": json})
        return TokenPlanResponse()


def test_minimax_token_plan_uses_anthropic_protocol(api: dict, monkeypatch) -> None:
    client: TestClient = api["client"]
    settings = api["app"].state.settings
    settings.minimax_api_key = "sk-cp-test.key"
    settings.minimax_access_mode = "token_plan"
    TokenPlanClient.calls.clear()
    monkeypatch.setattr(ai_service.httpx, "Client", TokenPlanClient)

    csrf = login(client, "member")
    status = client.get("/api/v1/ai/status")
    assert status.json() == {
        "configured": True,
        "provider": "MiniMax",
        "model": "MiniMax-M2.7",
    }
    response = client.post(
        "/api/v1/ai/chat",
        headers={"X-CSRF-Token": csrf},
        json={"prompt": "检查连接"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "Token Plan 连接正常。"
    assert response.json()["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 5,
        "total_tokens": 17,
    }
    call = TokenPlanClient.calls[-1]
    assert call["url"] == "https://api.minimaxi.com/anthropic/v1/messages"
    assert call["headers"]["x-api-key"] == "sk-cp-test.key"
    assert "Authorization" not in call["headers"]
    assert call["json"]["system"]
    assert call["json"]["messages"] == [{"role": "user", "content": "检查连接"}]


def test_admin_can_test_then_save_encrypted_provider_configuration(
    api: dict,
    monkeypatch,
) -> None:
    client: TestClient = api["client"]
    ProviderClient.calls.clear()
    monkeypatch.setattr(ai_service.httpx, "Client", ProviderClient)

    login(client, "member")
    forbidden = client.get("/api/v1/ai/configuration")
    assert forbidden.status_code == 403

    super_csrf = login(client, "super_admin")
    assert client.get("/api/v1/ai/configuration").status_code == 200
    assert super_csrf

    csrf = login(client, "admin")
    providers = client.get("/api/v1/ai/providers")
    assert providers.status_code == 200
    assert {item["id"] for item in providers.json()} == {
        "deepseek",
        "glm",
        "kimi",
        "minimax",
    }
    minimax = next(item for item in providers.json() if item["id"] == "minimax")
    assert minimax["default_access_mode"] == "token_plan"
    assert {item["id"] for item in minimax["access_modes"]} == {
        "token_plan",
        "pay_as_you_go",
    }

    initial = client.get("/api/v1/ai/configuration")
    assert initial.json()["source"] == "none"
    assert initial.json()["encryption_ready"] is True

    secret = "deepseek-test-secret-key"
    original_config_secret = api["app"].state.settings.llm_config_secret
    api["app"].state.settings.llm_config_secret = ""
    blocked_test = client.post(
        "/api/v1/ai/configuration/test",
        headers={"X-CSRF-Token": csrf},
        json={
            "provider": "deepseek",
            "access_mode": "standard",
            "model": "deepseek-v4-flash",
            "api_key": secret,
        },
    )
    assert blocked_test.status_code == 503
    assert blocked_test.json()["code"] == "AI_CONFIG_SECRET_MISSING"
    assert ProviderClient.calls == []
    api["app"].state.settings.llm_config_secret = original_config_secret

    mismatched_key = client.post(
        "/api/v1/ai/configuration/test",
        headers={"X-CSRF-Token": csrf},
        json={
            "provider": "minimax",
            "access_mode": "token_plan",
            "model": "MiniMax-M2.7",
            "api_key": "ordinary-api-key-not-token-plan",
        },
    )
    assert mismatched_key.status_code == 400
    assert mismatched_key.json()["code"] == "AI_API_KEY_MODE_MISMATCH"
    assert ProviderClient.calls == []

    validation = client.put(
        "/api/v1/ai/configuration",
        headers={"X-CSRF-Token": csrf},
        json={
            "provider": "deepseek",
            "access_mode": "standard",
            "model": "deepseek-v4-flash",
            "api_key": secret,
        },
    )
    assert validation.status_code == 422
    assert secret not in validation.text

    tested = client.post(
        "/api/v1/ai/configuration/test",
        headers={"X-CSRF-Token": csrf},
        json={
            "provider": "deepseek",
            "access_mode": "standard",
            "model": "deepseek-v4-flash",
            "api_key": secret,
        },
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["success"] is True
    assert tested.json()["usage"]["total_tokens"] == 10
    assert secret not in tested.text
    assert ProviderClient.calls[-1]["url"] == "https://api.deepseek.com/chat/completions"

    saved = client.put(
        "/api/v1/ai/configuration",
        headers={"X-CSRF-Token": csrf},
        json={
            "provider": "deepseek",
            "access_mode": "standard",
            "model": "deepseek-v4-flash",
            "api_key": secret,
            "verification_token": tested.json()["verification_token"],
            "revision": None,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["source"] == "database"
    assert saved.json()["provider_name"] == "DeepSeek"
    assert saved.json()["access_mode"] == "standard"
    assert saved.json()["api_key_hint"].endswith(secret[-4:])
    assert secret not in saved.text

    with api["app"].state.session_factory() as db:
        stored = db.scalar(select(AIProviderConfig))
        assert stored is not None
        assert stored.access_mode == "standard"
        assert secret not in stored.encrypted_api_key

    csrf = login(client, "member")
    status = client.get("/api/v1/ai/status")
    assert status.json() == {
        "configured": True,
        "provider": "DeepSeek",
        "model": "deepseek-v4-flash",
    }
    chat = client.post(
        "/api/v1/ai/chat",
        headers={"X-CSRF-Token": csrf},
        json={"prompt": "下一步做什么？"},
    )
    assert chat.status_code == 200, chat.text
    assert chat.json()["answer"] == "建议先确认项目范围。"
    assert ProviderClient.calls[-1]["headers"]["Authorization"] == f"Bearer {secret}"
