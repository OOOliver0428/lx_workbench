from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError

from app.api.router import api_router
from app.config import Settings, get_settings
from app.database import create_database_engine, create_session_factory
from app.errors import AppError
from app.schemas import ErrorResponse
from app.throttle import LoginThrottle


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_database_engine(settings)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        yield
        engine.dispose()

    app = FastAPI(
        title="团队项目管理 MVP API",
        version="0.1.0",
        lifespan=lifespan,
        responses={
            status_code: {"model": ErrorResponse}
            for status_code in (400, 401, 403, 404, 409, 422, 429, 502, 503)
        },
    )
    app.state.settings = settings
    app.state.login_throttle = LoginThrottle()

    if settings.allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, error: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "code": error.code,
                "message": error.message,
                "request_id": getattr(request.state, "request_id", None),
                "details": error.details or None,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        errors = []
        sensitive_fields = {
            "api_key",
            "password",
            "current_password",
            "new_password",
            "verification_token",
        }
        for item in error.errors():
            sanitized = dict(item)
            if any(str(part) in sensitive_fields for part in item.get("loc", ())):
                sanitized["input"] = "[REDACTED]"
            errors.append(sanitized)
        return JSONResponse(
            status_code=422,
            content={
                "code": "VALIDATION_ERROR",
                "message": "请求参数不符合要求",
                "request_id": getattr(request.state, "request_id", None),
                "details": {"errors": errors},
            },
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, _error: IntegrityError) -> JSONResponse:
        logging.getLogger(__name__).exception("database integrity error")
        return JSONResponse(
            status_code=409,
            content={
                "code": "DATABASE_CONSTRAINT_CONFLICT",
                "message": "数据与现有记录冲突",
                "request_id": getattr(request.state, "request_id", None),
                "details": None,
            },
        )

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    app.include_router(api_router)
    return app


app = create_app()
