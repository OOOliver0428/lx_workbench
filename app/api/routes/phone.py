from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.dependencies import get_current_session, get_db, require_csrf_session
from app.errors import AppError
from app.models import AuthSession, User
from app.phone.crypto import normalize_phone

router = APIRouter(prefix="/profile/phone", tags=["profile"])


class CaptchaConfigOut(BaseModel):
    region: str
    prefix: str
    scene_id: str


class ProfilePhoneOut(BaseModel):
    availability: str
    bound: bool
    phone_masked: str | None
    verified_at: datetime | None
    revision: int
    retry_after: int
    captcha: CaptchaConfigOut | None


class SendPhoneCode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone_number: str = Field(min_length=11, max_length=20)
    captcha_verify_param: str = Field(min_length=1, max_length=16000)

    @field_validator("phone_number")
    @classmethod
    def normalize(cls, value: str) -> str:
        return normalize_phone(value)


class ChallengeOut(BaseModel):
    challenge_id: str
    expires_at: datetime
    retry_after: int


class VerifyPhoneCode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sms_code: str = Field(pattern=r"^[0-9]{6}$")
    revision: int = Field(ge=1)
    current_password: str | None = Field(default=None, min_length=1, max_length=256)


def detach_actor(auth: tuple[AuthSession, User], db: Session) -> tuple[str, str]:
    session, user = auth
    if user.must_change_password:
        raise AppError("PASSWORD_CHANGE_REQUIRED", "请先修改初始密码", status_code=403)
    ids = user.id, session.id
    # Do not hold the authentication dependency's connection while waiting on a provider.
    db.close()
    return ids


@router.get("", response_model=ProfilePhoneOut)
async def phone_status(
    request: Request,
    auth: tuple[AuthSession, User] = Depends(get_current_session),
    db: Session = Depends(get_db, scope="function"),
):
    user_id, session_id = detach_actor(auth, db)
    service = request.app.state.phone_service
    return await service.run(service.status, user_id, session_id)


@router.post("/challenges", response_model=ChallengeOut)
async def send_phone_code(
    payload: SendPhoneCode,
    request: Request,
    auth: tuple[AuthSession, User] = Depends(require_csrf_session),
    db: Session = Depends(get_db, scope="function"),
):
    user_id, session_id = detach_actor(auth, db)
    service = request.app.state.phone_service
    return await service.run(
        service.send, user_id, session_id, payload.phone_number, payload.captcha_verify_param
    )


@router.post("/challenges/{challenge_id}/verify", response_model=ProfilePhoneOut)
async def verify_phone_code(
    challenge_id: str,
    payload: VerifyPhoneCode,
    request: Request,
    auth: tuple[AuthSession, User] = Depends(require_csrf_session),
    db: Session = Depends(get_db, scope="function"),
):
    user_id, session_id = detach_actor(auth, db)
    service = request.app.state.phone_service
    return await service.run(
        service.verify,
        user_id,
        session_id,
        challenge_id,
        payload.sms_code,
        payload.revision,
        payload.current_password,
        request.state.request_id,
    )
