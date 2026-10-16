import re

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 64 * 1024
MAX_IMAGE_PIXELS = 20_000_000
AVATAR_SIZE = 512
MAX_SAVED_BYTES = 1024 * 1024
UPLOAD_PATH = "/api/v1/profile/avatar/upload"


class AvatarSettings(BaseSettings):
    # Optional configuration must never prevent the core application from starting.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    enabled: bool = Field(False, alias="MVP_CUSTOM_AVATAR_ENABLED")
    secret_id: SecretStr = Field(SecretStr(""), alias="MVP_AVATAR_COS_SECRET_ID")
    secret_key: SecretStr = Field(SecretStr(""), alias="MVP_AVATAR_COS_SECRET_KEY")
    bucket: str = Field("", alias="MVP_AVATAR_COS_BUCKET")
    region: str = Field("", alias="MVP_AVATAR_COS_REGION")
    prefix: str = Field("avatars/", alias="MVP_AVATAR_COS_PREFIX")

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, value: str) -> str:
        if value and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,61}-[0-9]+", value):
            raise ValueError("invalid COS bucket")
        return value

    @field_validator("region")
    @classmethod
    def validate_region(cls, value: str) -> str:
        if value and not re.fullmatch(r"[a-z]+(?:-[a-z0-9]+)+", value):
            raise ValueError("invalid COS region")
        return value

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        value = value.rstrip("/")
        if (
            not value
            or len(value) > 200
            or not re.fullmatch(r"[a-zA-Z0-9_/-]+", value)
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("invalid avatar prefix")
        return value + "/"

    def configured(self) -> bool:
        return bool(
            self.secret_id.get_secret_value()
            and self.secret_key.get_secret_value()
            and self.bucket
            and self.region
        )
