from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.custom_avatars.config import MAX_UPLOAD_BYTES
from app.custom_avatars.images import AvatarCrop
from app.dependencies import get_current_session, get_db, require_csrf_session
from app.errors import AppError
from app.models import AuthSession, User
from app.schemas import UserOut

router = APIRouter(tags=["profile"])


class AvatarStatusOut(BaseModel):
    availability: Literal["ready", "disabled", "unavailable"]
    phone_bound: bool
    can_upload: bool
    max_file_bytes: int
    output_size: int
    formats: list[str]


def detach(auth: tuple[AuthSession, User], db: Session) -> tuple[str, str]:
    session, user = auth
    if user.must_change_password:
        raise AppError("PASSWORD_CHANGE_REQUIRED", "请先修改初始密码", status_code=403)
    ids = user.id, session.id
    db.close()
    return ids


@router.get("/profile/avatar/status", response_model=AvatarStatusOut)
async def avatar_status(
    request: Request,
    auth: Annotated[tuple[AuthSession, User], Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db, scope="function")],
):
    ids = detach(auth, db)
    service = request.app.state.avatar_service
    return await service.run(service.status, *ids)


@router.post("/profile/avatar/upload", response_model=UserOut)
async def upload_avatar(
    request: Request,
    auth: Annotated[tuple[AuthSession, User], Depends(require_csrf_session)],
    db: Annotated[Session, Depends(get_db, scope="function")],
    file: Annotated[UploadFile, File()],
    revision: Annotated[int, Form(ge=1)],
    crop: Annotated[str, Form(max_length=512)],
):
    ids = detach(auth, db)
    try:
        try:
            parsed_crop = AvatarCrop.model_validate_json(crop)
        except ValidationError:
            raise AppError("AVATAR_INVALID_CROP", "裁剪参数不正确", status_code=422) from None
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise AppError("AVATAR_FILE_TOO_LARGE", "请选择不超过 5 MiB 的图片", status_code=413)
        service = request.app.state.avatar_service
        return await service.run(
            service.upload, *ids, revision, data, parsed_crop, request.state.request_id, upload=True
        )
    finally:
        await file.close()


@router.get("/avatars/{asset_id}")
async def avatar_image(
    asset_id: str,
    request: Request,
    auth: Annotated[tuple[AuthSession, User], Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db, scope="function")],
):
    ids = detach(auth, db)
    if len(asset_id) != 32 or any(char not in "0123456789abcdef" for char in asset_id):
        raise AppError("AVATAR_NOT_FOUND", "头像不存在", status_code=404)
    service = request.app.state.avatar_service
    data = await service.run(service.image, *ids, asset_id)
    return Response(data, media_type="image/webp")
