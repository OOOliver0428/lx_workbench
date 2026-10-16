from __future__ import annotations

import logging
from typing import Protocol

from app.custom_avatars.config import MAX_SAVED_BYTES, AvatarSettings


class AvatarStorage(Protocol):
    def put(self, bucket: str, region: str, key: str, data: bytes) -> str | None: ...

    def get(self, bucket: str, region: str, key: str) -> bytes: ...

    def delete(self, bucket: str, region: str, key: str, version_id: str | None) -> None: ...


class CosAvatarStorage:
    def __init__(self, settings: AvatarSettings):
        # Imported lazily; core paths do not initialize or contact COS.
        from qcloud_cos import CosConfig, CosS3Client

        # The SDK logs signed headers and exception details; expose only our safe error codes.
        for name in ("qcloud_cos.cos_client", "qcloud_cos.cos_auth"):
            logging.getLogger(name).disabled = True
        config = CosConfig(
            Region=settings.region,
            SecretId=settings.secret_id.get_secret_value(),
            SecretKey=settings.secret_key.get_secret_value(),
            Scheme="https",
            Timeout=10,
            AllowRedirects=False,
            VerifySSL=True,
        )
        self.region = settings.region
        self.client = CosS3Client(config, retry=1)

    def check_region(self, region: str) -> None:
        if region != self.region:
            raise ValueError("avatar resource belongs to a different COS region")

    def put(self, bucket: str, region: str, key: str, data: bytes) -> str | None:
        self.check_region(region)
        response = self.client.put_object(
            Bucket=bucket, Key=key, Body=data, ContentType="image/webp", EnableMD5=True
        )
        return response.get("x-cos-version-id")

    def get(self, bucket: str, region: str, key: str) -> bytes:
        self.check_region(region)
        response = self.client.get_object(Bucket=bucket, Key=key)
        stream = response["Body"].get_raw_stream()
        try:
            data = stream.read(MAX_SAVED_BYTES + 1)
        finally:
            stream.close()
        if not data or len(data) > MAX_SAVED_BYTES:
            raise ValueError("invalid stored avatar size")
        return data

    def delete(self, bucket: str, region: str, key: str, version_id: str | None) -> None:
        self.check_region(region)
        params = {"VersionId": version_id} if version_id else {}
        self.client.delete_object(Bucket=bucket, Key=key, **params)
