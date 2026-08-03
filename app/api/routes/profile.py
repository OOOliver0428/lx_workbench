from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.avatars import AVATAR_KEYS, AVATAR_OPTIONS
from app.dependencies import get_current_user, get_db, require_csrf
from app.errors import AppError, ConflictError
from app.models import User, utc_now
from app.schemas import AvatarOptionOut, ProfileAvatarUpdate, UserOut

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("/avatars", response_model=list[AvatarOptionOut])
def list_avatar_options(
    _actor: User = Depends(get_current_user),
) -> list[AvatarOptionOut]:
    return [AvatarOptionOut(**option) for option in AVATAR_OPTIONS]


@router.patch("/avatar", response_model=UserOut)
def update_my_avatar(
    payload: ProfileAvatarUpdate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> UserOut:
    if payload.revision != actor.revision:
        raise ConflictError(
            "REVISION_CONFLICT",
            "个人资料已发生变化，请刷新后重试",
            {
                "expected_revision": payload.revision,
                "current_revision": actor.revision,
            },
        )
    if payload.avatar_key is not None and payload.avatar_key not in AVATAR_KEYS:
        raise AppError("AVATAR_NOT_FOUND", "所选头像不在系统头像库中")
    previous_avatar_key = actor.avatar_key
    if previous_avatar_key == payload.avatar_key:
        return UserOut.model_validate(actor)

    actor.avatar_key = payload.avatar_key
    actor.revision += 1
    actor.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="profile.avatar.update",
        entity_type="user",
        entity_id=actor.id,
        before_data={"avatarKey": previous_avatar_key},
        after_data={"avatarKey": actor.avatar_key, "revision": actor.revision},
    )
    return UserOut.model_validate(actor)
