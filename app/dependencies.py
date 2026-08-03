from __future__ import annotations

import hmac
from collections.abc import Iterator
from datetime import UTC, datetime

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.errors import AppError, PermissionDeniedError
from app.models import AuthSession, User
from app.security import hash_session_token


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def get_db(request: Request) -> Iterator[Session]:
    db: Session = request.app.state.session_factory()
    db.info["request_id"] = getattr(request.state, "request_id", None)
    db.info["client_ip"] = request.client.host if request.client else None
    try:
        yield db
        db.commit()
    except StaleDataError as error:
        db.rollback()
        raise AppError(
            "REVISION_CONFLICT",
            "数据已被其他操作更新，请刷新后重试",
            status_code=409,
        ) from error
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_current_session(
    request: Request,
    db: Session = Depends(get_db, scope="function"),
) -> tuple[AuthSession, User]:
    cookie_name = request.app.state.settings.session_cookie_name
    token = request.cookies.get(cookie_name)
    if not token:
        raise AppError("AUTH_REQUIRED", "请先登录", status_code=401)

    token_hash = hash_session_token(token)
    auth_session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == token_hash,
            AuthSession.revoked_at.is_(None),
        )
    )
    if not auth_session or ensure_aware(auth_session.expires_at) <= utc_now():
        raise AppError("SESSION_EXPIRED", "登录已失效，请重新登录", status_code=401)

    user = db.get(User, auth_session.user_id)
    if not user or not user.is_active:
        raise AppError("ACCOUNT_DISABLED", "账号已停用", status_code=401)

    return auth_session, user


def get_current_user(
    auth: tuple[AuthSession, User] = Depends(get_current_session),
) -> User:
    user = auth[1]
    if user.must_change_password:
        raise AppError(
            "PASSWORD_CHANGE_REQUIRED",
            "首次登录必须先修改初始密码",
            status_code=403,
        )
    return user


def require_csrf_session(
    request: Request,
    auth: tuple[AuthSession, User] = Depends(get_current_session),
) -> tuple[AuthSession, User]:
    auth_session, user = auth
    received = request.headers.get("X-CSRF-Token", "")
    if not received or not hmac.compare_digest(received, auth_session.csrf_token):
        raise AppError("CSRF_VALIDATION_FAILED", "请求校验失败", status_code=403)
    return auth_session, user


def require_csrf(
    auth: tuple[AuthSession, User] = Depends(require_csrf_session),
) -> User:
    _auth_session, user = auth
    if user.must_change_password:
        raise AppError(
            "PASSWORD_CHANGE_REQUIRED",
            "首次登录必须先修改初始密码",
            status_code=403,
        )
    return user


def require_admin(user: User = Depends(require_csrf)) -> User:
    if user.role not in {"system_admin", "super_admin"}:
        raise PermissionDeniedError()
    return user


def require_admin_read(user: User = Depends(get_current_user)) -> User:
    if user.role not in {"system_admin", "super_admin"}:
        raise PermissionDeniedError()
    return user


def require_privileged(user: User = Depends(require_csrf)) -> User:
    if user.role not in {"team_leader", "system_admin", "super_admin"}:
        raise PermissionDeniedError()
    return user


def require_privileged_read(user: User = Depends(get_current_user)) -> User:
    if user.role not in {"team_leader", "system_admin", "super_admin"}:
        raise PermissionDeniedError()
    return user
