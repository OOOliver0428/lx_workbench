from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.audit import record_audit
from app.custom_avatars.config import AVATAR_SIZE, MAX_UPLOAD_BYTES, AvatarSettings
from app.custom_avatars.images import AvatarCrop, process_image
from app.custom_avatars.storage import AvatarStorage, CosAvatarStorage
from app.errors import AppError, ConflictError
from app.models import AuthSession, AvatarAsset, User, utc_now
from app.schemas import UserOut

LOG = logging.getLogger(__name__)
CUSTOM_KEY = re.compile(r"^custom-([0-9a-f]{32})$")
RETENTION = timedelta(hours=24)
CACHE_BYTES = 16 * 1024 * 1024


def unavailable() -> AppError:
    return AppError("AVATAR_STORAGE_UNAVAILABLE", "自定义头像暂不可用，请稍后重试", status_code=503)


def phone_bound(user: User) -> bool:
    # Local verified state only: no decryption, provider request or phone-module switch.
    return all(
        value is not None
        for value in (
            user.phone_verified_at,
            user.phone_lookup_hash,
            user.phone_ciphertext,
            user.phone_key_id,
        )
    )


def retire_avatar(db: Session, avatar_key: str | None) -> None:
    match = CUSTOM_KEY.fullmatch(avatar_key or "")
    if match:
        asset = db.get(AvatarAsset, match[1])
        if asset and asset.state == "active":
            asset.state = "retired"
            asset.cleanup_after = utc_now() + RETENTION


class AvatarService:
    def __init__(
        self,
        factory: sessionmaker[Session],
        settings: AvatarSettings | None = None,
        storage: AvatarStorage | None = None,
    ):
        self.factory, self.settings, self.storage = factory, settings, storage
        self.init_lock = threading.Lock()
        self.upload_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="avatar-upload")
        self.read_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="avatar-read")
        self.upload_slots = threading.BoundedSemaphore(2)
        # Four workers plus a bounded queue accommodate lists loading several avatars at once.
        self.read_slots = threading.BoundedSemaphore(32)
        self.cache: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self.cache_size = 0
        self.cache_lock = threading.Lock()
        self.cleanup_lock = threading.Lock()
        self.stop = threading.Event()
        self.cleanup_thread: threading.Thread | None = None

    def start(self) -> None:
        self.cleanup_thread = threading.Thread(
            target=self.cleanup_loop, name="avatar-cleanup", daemon=True
        )
        self.cleanup_thread.start()

    def close(self) -> None:
        self.stop.set()
        if self.cleanup_thread:
            self.cleanup_thread.join(timeout=1)
        self.upload_executor.shutdown(wait=False, cancel_futures=True)
        self.read_executor.shutdown(wait=False, cancel_futures=True)

    def config(self) -> AvatarSettings:
        with self.init_lock:
            if self.settings is None:
                self.settings = AvatarSettings()
            return self.settings

    def ready(self) -> tuple[AvatarSettings, AvatarStorage]:
        settings = self.config()
        if not settings.enabled or not settings.configured():
            raise unavailable()
        with self.init_lock:
            if self.storage is None:
                self.storage = CosAvatarStorage(settings)
            return settings, self.storage

    async def run(self, method: Callable[..., Any], *args: Any, upload: bool = False) -> Any:
        slots = self.upload_slots if upload else self.read_slots
        executor = self.upload_executor if upload else self.read_executor
        if not slots.acquire(blocking=False):
            raise AppError("AVATAR_BUSY", "头像服务繁忙，请稍后重试", status_code=429)

        def work():
            try:
                return method(*args)
            except AppError:
                raise
            except Exception:
                # SDK exceptions may embed credentials, request signatures and object paths.
                LOG.warning("avatar operation failed; sensitive exception details suppressed")
                raise unavailable() from None

        try:
            future = executor.submit(work)
        except Exception:
            slots.release()
            raise unavailable() from None
        # The underlying future owns the slot, including cancellation before work starts.
        future.add_done_callback(lambda _future: slots.release())
        return await asyncio.wrap_future(future)

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self.factory() as db:
            try:
                if db.bind.dialect.name == "sqlite":
                    db.execute(text("BEGIN IMMEDIATE"))
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    @staticmethod
    def actor(db: Session, user_id: str, session_id: str) -> User:
        auth = db.get(AuthSession, session_id)
        user = db.get(User, user_id)
        if (
            not auth
            or auth.user_id != user_id
            or auth.revoked_at
            or auth.expires_at <= utc_now()
            or not user
            or not user.is_active
        ):
            raise AppError("SESSION_EXPIRED", "登录已失效，请重新登录", status_code=401)
        if user.must_change_password:
            raise AppError("PASSWORD_CHANGE_REQUIRED", "请先修改初始密码", status_code=403)
        return user

    @staticmethod
    def check_upload(user: User, revision: int) -> None:
        if not phone_bound(user):
            raise AppError(
                "AVATAR_PHONE_REQUIRED", "请先完成手机号绑定，再上传自定义头像", status_code=403
            )
        if user.revision != revision:
            raise ConflictError("REVISION_CONFLICT", "个人资料已更新，请刷新后重试")

    def status(self, user_id: str, session_id: str) -> dict:
        with self.factory() as db:
            user = self.actor(db, user_id, session_id)
            result = dict(
                availability="unavailable",
                phone_bound=phone_bound(user),
                can_upload=False,
                max_file_bytes=MAX_UPLOAD_BYTES,
                output_size=AVATAR_SIZE,
                formats=["JPEG", "PNG", "WEBP"],
            )
        try:
            settings = self.config()
            result["availability"] = (
                "disabled"
                if not settings.enabled
                else "ready"
                if settings.configured()
                else "unavailable"
            )
        except Exception:
            pass
        result["can_upload"] = result["phone_bound"] and result["availability"] == "ready"
        return result

    def upload(
        self,
        user_id: str,
        session_id: str,
        revision: int,
        data: bytes,
        crop: AvatarCrop,
        request_id: str,
    ) -> UserOut:
        settings, storage = self.ready()
        asset_id = uuid.uuid4().hex
        object_key = settings.prefix + asset_id + ".webp"
        with self.transaction() as db:
            user = self.actor(db, user_id, session_id)
            self.check_upload(user, revision)
            count = db.scalar(
                select(func.count())
                .select_from(AvatarAsset)
                .where(
                    AvatarAsset.user_id == user_id,
                    AvatarAsset.created_at > utc_now() - timedelta(hours=1),
                )
            )
            if count >= 10:
                raise AppError(
                    "AVATAR_RATE_LIMITED", "头像修改过于频繁，请稍后重试", status_code=429
                )
            db.add(
                AvatarAsset(
                    id=asset_id,
                    user_id=user_id,
                    bucket=settings.bucket,
                    region=settings.region,
                    object_key=object_key,
                    state="pending",
                    cleanup_after=utc_now() + RETENTION,
                )
            )
        # Pending row is durable before any external write, including ambiguous timeouts.
        encoded = process_image(data, crop)
        version_id = storage.put(settings.bucket, settings.region, object_key, encoded)
        # Persist the acknowledged version even if subsequent profile checks/commit fail.
        with self.transaction() as db:
            asset = db.get(AvatarAsset, asset_id)
            if not asset or asset.state != "pending":
                raise ConflictError("AVATAR_UPLOAD_EXPIRED", "上传已失效，请重新选择图片")
            asset.version_id = version_id
            asset.size_bytes = len(encoded)
            asset.sha256 = hashlib.sha256(encoded).hexdigest()
            asset.width = asset.height = AVATAR_SIZE
        with self.transaction() as db:
            user = self.actor(db, user_id, session_id)
            self.check_upload(user, revision)
            asset = db.get(AvatarAsset, asset_id)
            if not asset or asset.state != "pending":
                raise ConflictError("AVATAR_UPLOAD_EXPIRED", "上传已失效，请重新选择图片")
            previous = user.avatar_key
            retire_avatar(db, previous)
            asset.state = "active"
            asset.cleanup_after = None
            user.avatar_key = "custom-" + asset_id
            user.revision += 1
            user.updated_at = utc_now()
            db.info["request_id"] = request_id
            record_audit(
                db,
                actor=user,
                action="profile.avatar.update",
                entity_type="user",
                entity_id=user.id,
                before_data={"avatarKey": previous},
                after_data={"avatarKey": user.avatar_key, "revision": user.revision},
            )
            db.flush()
            result = UserOut.model_validate(user)
        return result

    def image(self, user_id: str, session_id: str, asset_id: str) -> bytes:
        with self.factory() as db:
            self.actor(db, user_id, session_id)
            asset = db.get(AvatarAsset, asset_id)
            current = db.scalar(select(User.id).where(User.avatar_key == "custom-" + asset_id))
            if not asset or asset.state != "active" or not current:
                raise AppError("AVATAR_NOT_FOUND", "头像不存在", status_code=404)
            bucket, region, key, sha256 = asset.bucket, asset.region, asset.object_key, asset.sha256
        # Authentication and current-reference checks precede even a cache hit.
        _settings, storage = self.ready()
        with self.cache_lock:
            cached = self.cache.get(asset_id)
            if cached and cached[0] > time.monotonic():
                self.cache.move_to_end(asset_id)
                return cached[1]
        data = storage.get(bucket, region, key)
        if hashlib.sha256(data).hexdigest() != sha256:
            raise unavailable()
        with self.cache_lock:
            old = self.cache.pop(asset_id, None)
            if old:
                self.cache_size -= len(old[1])
            self.cache[asset_id] = (time.monotonic() + 300, data)
            self.cache_size += len(data)
            while self.cache_size > CACHE_BYTES:
                _key, (_expires, removed) = self.cache.popitem(last=False)
                self.cache_size -= len(removed)
        return data

    def cleanup_loop(self) -> None:
        if self.stop.wait(60):
            return
        while not self.stop.is_set():
            try:
                self.cleanup()
            except Exception:
                LOG.warning("avatar cleanup failed; sensitive exception details suppressed")
            if self.stop.wait(3600):
                return

    def cleanup(self) -> int:
        # No COS calls or DB access if the optional module is disabled/unconfigured.
        settings = self.config()
        if not settings.enabled or not settings.configured():
            return 0
        _settings, storage = self.ready()
        if not self.cleanup_lock.acquire(blocking=False):
            return 0
        removed = 0
        try:
            with self.factory() as db:
                ids = list(
                    db.scalars(
                        select(AvatarAsset.id)
                        .where(AvatarAsset.cleanup_after <= utc_now())
                        .order_by(AvatarAsset.cleanup_after)
                        .limit(100)
                    )
                )
            for asset_id in ids:
                if self.stop.is_set():
                    break
                with self.transaction() as db:
                    asset = db.get(AvatarAsset, asset_id)
                    if not asset or not asset.cleanup_after or asset.cleanup_after > utc_now():
                        continue
                    if db.scalar(select(User.id).where(User.avatar_key == "custom-" + asset_id)):
                        # Repair metadata rather than deleting a referenced image.
                        asset.state, asset.cleanup_after = "active", None
                        continue
                    asset.state = "deleting"
                    bucket, region, key, version = (
                        asset.bucket,
                        asset.region,
                        asset.object_key,
                        asset.version_id,
                    )
                try:
                    storage.delete(bucket, region, key, version)
                except Exception:
                    with self.transaction() as db:
                        asset = db.get(AvatarAsset, asset_id)
                        if asset:
                            asset.cleanup_after = utc_now() + timedelta(hours=1)
                    LOG.warning("avatar deletion failed; retry scheduled")
                    continue
                with self.transaction() as db:
                    asset = db.get(AvatarAsset, asset_id)
                    if asset:
                        db.delete(asset)
                with self.cache_lock:
                    cached = self.cache.pop(asset_id, None)
                    if cached:
                        self.cache_size -= len(cached[1])
                removed += 1
        finally:
            self.cleanup_lock.release()
        return removed
