from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_unhandled_errors_keep_the_uniform_contract_and_security_headers(
    tmp_path,
) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'errors.db').as_posix()}",
        allowed_hosts_csv="testserver",
        cookie_secure=False,
        llm_config_secret="test-only-llm-config-secret-at-least-32-characters",
    )
    app: FastAPI = create_app(settings)

    @app.get("/__test_unhandled")
    def fail_deliberately() -> None:
        raise RuntimeError("sensitive implementation detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/__test_unhandled",
            headers={"X-Request-ID": "qa-unhandled-request"},
        )

    assert response.status_code == 500
    assert response.json() == {
        "code": "INTERNAL_SERVER_ERROR",
        "message": "系统暂时无法处理该请求",
        "request_id": "qa-unhandled-request",
        "details": None,
    }
    assert "sensitive implementation detail" not in response.text
    assert response.headers["X-Request-ID"] == "qa-unhandled-request"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"


def test_framework_404_and_405_errors_keep_the_uniform_contract(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'http-errors.db').as_posix()}",
        allowed_hosts_csv="testserver",
        cookie_secure=False,
        llm_config_secret="test-only-llm-config-secret-at-least-32-characters",
    )
    app: FastAPI = create_app(settings)

    with TestClient(app) as client:
        not_found = client.get(
            "/api/v1/does-not-exist",
            headers={"X-Request-ID": "qa-http-not-found"},
        )
        method_not_allowed = client.post(
            "/api/v1/health/live",
            headers={"X-Request-ID": "qa-http-method"},
        )

    assert not_found.status_code == 404
    assert not_found.json() == {
        "code": "RESOURCE_NOT_FOUND",
        "message": "请求的资源不存在",
        "request_id": "qa-http-not-found",
        "details": None,
    }
    assert method_not_allowed.status_code == 405
    assert method_not_allowed.json() == {
        "code": "METHOD_NOT_ALLOWED",
        "message": "请求方法不被允许",
        "request_id": "qa-http-method",
        "details": None,
    }
    assert method_not_allowed.headers["Allow"] == "GET"
    for response in (not_found, method_not_allowed):
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["Cache-Control"] == "no-store"
