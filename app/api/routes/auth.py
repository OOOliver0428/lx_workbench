from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.dependencies import get_current_session, get_db, require_csrf_session
from app.errors import AppError
from app.models import AuthSession, User, utc_now
from app.schemas import AuthContextOut, LoginRequest, PasswordChange
from app.security import (
    generate_csrf_token,
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=AuthContextOut)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthContextOut:
    throttle = request.app.state.login_throttle
    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}:{payload.login_name.casefold()}"
    if throttle.is_blocked(key):
        raise AppError("LOGIN_RATE_LIMITED", "登录失败次数过多，请稍后再试", status_code=429)

    user = db.scalar(select(User).where(User.login_name == payload.login_name.strip().casefold()))
    if not user or not user.is_active or not verify_password(user.password_hash, payload.password):
        throttle.record_failure(key)
        record_audit(
            db,
            actor=user,
            action="auth.login",
            entity_type="user",
            entity_id=user.id if user else None,
            result="failure",
            detail={"loginName": payload.login_name.strip()},
        )
        raise AppError("INVALID_CREDENTIALS", "用户名或密码错误", status_code=401)

    throttle.clear(key)
    token = generate_session_token()
    csrf_token = generate_csrf_token()
    expires_at = utc_now() + timedelta(hours=request.app.state.settings.session_ttl_hours)
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        csrf_token=csrf_token,
        expires_at=expires_at,
        client_ip=client_ip,
        user_agent=(request.headers.get("user-agent") or "")[:512],
    )
    db.add(auth_session)
    user.last_login_at = utc_now()
    response.set_cookie(
        request.app.state.settings.session_cookie_name,
        token,
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="strict",
        max_age=request.app.state.settings.session_ttl_hours * 3600,
        path="/",
    )
    record_audit(
        db,
        actor=user,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
    )
    return AuthContextOut(
        user=user,
        csrf_token=csrf_token,
        expires_at=expires_at,
    )


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    auth: tuple[AuthSession, User] = Depends(require_csrf_session),
    db: Session = Depends(get_db),
) -> Response:
    auth_session, user = auth
    auth_session.revoked_at = utc_now()
    response.delete_cookie(request.app.state.settings.session_cookie_name, path="/")
    record_audit(
        db,
        actor=user,
        action="auth.logout",
        entity_type="user",
        entity_id=user.id,
    )
    return response


@router.get("/me", response_model=AuthContextOut)
def me(auth: tuple[AuthSession, User] = Depends(get_current_session)) -> AuthContextOut:
    auth_session, user = auth
    return AuthContextOut(
        user=user,
        csrf_token=auth_session.csrf_token,
        expires_at=auth_session.expires_at,
    )


@router.post("/change-password", status_code=204)
def change_password(
    payload: PasswordChange,
    auth: tuple[AuthSession, User] = Depends(require_csrf_session),
    db: Session = Depends(get_db),
) -> Response:
    auth_session, user = auth
    if not verify_password(user.password_hash, payload.current_password):
        raise AppError("INVALID_CURRENT_PASSWORD", "当前密码错误", status_code=400)
    changed_at = utc_now()
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.revision += 1
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.id != auth_session.id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=changed_at)
    )
    record_audit(
        db,
        actor=user,
        action="auth.password.change",
        entity_type="user",
        entity_id=user.id,
    )
    return Response(status_code=204)
