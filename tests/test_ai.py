from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import AIProviderConfig
from app.services import ai as ai_service
from tests.conftest import login


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
