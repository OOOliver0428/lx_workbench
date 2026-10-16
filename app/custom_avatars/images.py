from __future__ import annotations

import io
import math

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from app.custom_avatars.config import (
    AVATAR_SIZE,
    MAX_IMAGE_PIXELS,
    MAX_SAVED_BYTES,
    MAX_UPLOAD_BYTES,
)
from app.errors import AppError


class AvatarCrop(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    # Coordinates apply after EXIF orientation. Size is relative to the shorter side.
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    size: float = Field(gt=0, le=1)


def process_image(data: bytes, crop: AvatarCrop) -> bytes:
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise AppError("AVATAR_FILE_TOO_LARGE", "请选择不超过 5 MiB 的图片", status_code=413)
    try:
        with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as image:
            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS:
                raise AppError("AVATAR_TOO_MANY_PIXELS", "图片像素过多，请使用较小的图片")
            if getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) != 1:
                raise AppError("AVATAR_ANIMATED_IMAGE", "头像暂不支持动图，请选择静态图片")
            image.verify()
        with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as image:
            oriented = ImageOps.exif_transpose(image)
            width, height = oriented.size
            size = crop.size * min(width, height)
            left, top = crop.x * width, crop.y * height
            if size < 1 or left + size > width + 0.01 or top + size > height + 0.01:
                raise AppError("AVATAR_INVALID_CROP", "裁剪区域超出图片范围，请重新选择")
            edge = max(1, math.floor(size + 0.000001))
            x = min(math.floor(left + 0.000001), width - edge)
            y = min(math.floor(top + 0.000001), height - edge)
            result = oriented.crop((x, y, x + edge, y + edge)).convert("RGBA")
            result = result.resize((AVATAR_SIZE, AVATAR_SIZE), Image.Resampling.LANCZOS)
            # Save into a fresh image so EXIF, GPS, ICC and text chunks never survive.
            clean = Image.new("RGBA", result.size)
            clean.paste(result)
            output = io.BytesIO()
            clean.save(output, format="WEBP", quality=85, method=4)
            encoded = output.getvalue()
            if len(encoded) > MAX_SAVED_BYTES:
                raise AppError("AVATAR_INVALID_IMAGE", "图片处理失败，请换一张图片")
            return encoded
    except AppError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise AppError("AVATAR_TOO_MANY_PIXELS", "图片像素过多，请使用较小的图片") from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise AppError("AVATAR_INVALID_IMAGE", "请选择有效的 JPG、PNG 或静态 WebP 图片") from None
