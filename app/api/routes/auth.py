from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.audit import record_audit, record_audit_committed
from app.dependencies import get_current_session, get_db, require_csrf_session
from app.errors import AppError
from app.identity import normalize_user_identifier
from app.models import AuthSession, User, utc_now
from app.schemas import AuthContextOut, LoginRequest, PasswordChange
from app.security import (
    generate_csrf_token,
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
    verify_password_for_login,
)
from app.services.permissions import effective_permission_keys
from app.throttle import LoginCapacityExceeded

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=AuthContextOut)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db, scope="function"),
) -> AuthContextOut:
    throttle = request.app.state.login_throttle
    client_ip = request.client.host if request.client else "unknown"
    login_identifier = normalize_user_identifier(payload.login_name)
    try:
        with throttle.verification_slot(client_ip):
            user = db.scalar(
                select(User).where(
                    or_(
                        User.login_name == login_identifier,
                        User.display_name_key == login_identifier,
                    )
                )
            )
            can_authenticate = bool(user and user.is_active)
            password_matches = verify_password_for_login(
                user.password_hash if user else None,
                payload.password,
            )
    except LoginCapacityExceeded as error:
        raise AppError(
            "LOGIN_RATE_LIMITED",
            "登录请求过于频繁，请稍后再试",
            status_code=429,
        ) from error
    if not can_authenticate or not password_matches:
        failure = throttle.record_login_failure(client_ip, login_identifier)
        actor_id = user.id if user else None
        entity_id = user.id if user else None
        db.rollback()
        if failure.should_audit:
            settings = request.app.state.settings
            record_audit_committed(
                request.app.state.session_factory,
                actor_id=actor_id,
                action="auth.login",
                entity_type="user",
                entity_id=entity_id,
                request_id=getattr(request.state, "request_id", None),
                client_ip=client_ip,
                result="failure",
                detail={
                    "loginIdentifier": login_identifier,
                    "failureCount": failure.failure_count,
                    "suppressedAudits": failure.suppressed_audits,
                },
                login_failure_retention_days=(
                    settings.login_failure_audit_retention_days
                ),
                login_failure_max_rows=settings.login_failure_audit_max_rows,
            )
        if user and not user.is_active and password_matches:
            raise AppError(
                "ACCOUNT_FROZEN",
                "该账号已冻结，请联系系统管理员",
                status_code=401,
            )
        raise AppError(
            "INVALID_CREDENTIALS",
            "登录名、显示名称或密码错误",
            status_code=401,
        )

    throttle.clear_login(client_ip, login_identifier)
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
        permissions=effective_permission_keys(db, user),
        csrf_token=csrf_token,
        expires_at=expires_at,
    )


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    auth: tuple[AuthSession, User] = Depends(require_csrf_session),
    db: Session = Depends(get_db, scope="function"),
) -> Response:
    auth_session, user = auth
    auth_session.revoked_at = utc_now()
    response = Response(status_code=204)
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
def me(
    auth: tuple[AuthSession, User] = Depends(get_current_session),
    db: Session = Depends(get_db, scope="function"),
) -> AuthContextOut:
    auth_session, user = auth
    return AuthContextOut(
        user=user,
        permissions=effective_permission_keys(db, user),
        csrf_token=auth_session.csrf_token,
        expires_at=auth_session.expires_at,
    )


@router.post("/change-password", status_code=204)
def change_password(
    payload: PasswordChange,
    auth: tuple[AuthSession, User] = Depends(require_csrf_session),
    db: Session = Depends(get_db, scope="function"),
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
