from __future__ import annotations

import asyncio
import hmac
import logging
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.audit import record_audit
from app.errors import AppError
from app.models import AuthSession, PhoneChallenge, PhoneCryptoKeyCheck, User, new_id, utc_now
from app.phone.config import PhoneSettings
from app.phone.crypto import PhoneCrypto, normalize_phone
from app.phone.provider import AliyunPhoneProvider, PhoneProvider
from app.security import verify_password

LOG = logging.getLogger(__name__)


def unavailable() -> AppError:
    return AppError(
        "PHONE_VERIFICATION_UNAVAILABLE", "手机号认证暂不可用，请稍后重试", status_code=503
    )


def conflict(message: str = "个人资料已更新，请刷新后重试") -> AppError:
    return AppError("PHONE_VERIFICATION_CONFLICT", message, status_code=409)


class PhoneService:
    def __init__(
        self,
        factory: sessionmaker[Session],
        settings: PhoneSettings | None = None,
        provider: PhoneProvider | None = None,
    ):
        self.factory = factory
        self.settings = settings
        self.provider = provider
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="phone")
        self.slots = threading.BoundedSemaphore(2)
        self.init_lock = threading.Lock()

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    def config(self) -> PhoneSettings:
        if self.settings is None:
            with self.init_lock:
                if self.settings is None:
                    self.settings = PhoneSettings()
        return self.settings

    async def run(self, method: Callable[..., Any], *args: Any) -> Any:
        if not self.slots.acquire(blocking=False):
            raise AppError("PHONE_VERIFICATION_BUSY", "手机号认证繁忙，请稍后重试", status_code=429)

        # Release only after the actual worker ends, even if the HTTP request is cancelled.
        def work():
            try:
                return method(*args)
            except AppError:
                raise
            except Exception:
                # SDK/database exception strings may contain phone numbers or credentials.
                LOG.warning("phone operation failed; sensitive exception details suppressed")
                raise unavailable() from None
            finally:
                self.slots.release()

        return await asyncio.get_running_loop().run_in_executor(self.executor, work)

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

    def actor(self, db: Session, user_id: str, session_id: str) -> User:
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

    def crypto(self, db: Session) -> PhoneCrypto:
        crypto = PhoneCrypto(self.config())
        checks = {row.id: row.check_value for row in db.scalars(select(PhoneCryptoKeyCheck))}
        if "lookup" not in checks and (
            checks
            or db.scalar(
                select(User.id)
                .where(
                    or_(
                        User.phone_lookup_hash.is_not(None),
                        User.phone_ciphertext.is_not(None),
                        User.phone_verified_at.is_not(None),
                        User.phone_key_id.is_not(None),
                    )
                )
                .limit(1)
            )
            or db.scalar(select(PhoneChallenge.id).limit(1))
        ):
            raise unavailable()
        used_keys = set(db.scalars(select(User.phone_key_id).where(User.phone_key_id.is_not(None))))
        used_keys.update(db.scalars(select(PhoneChallenge.phone_key_id).distinct()))
        if not used_keys.issubset(crypto.keys):
            raise unavailable()
        for name, check in crypto.checks.items():
            if name in checks and not hmac.compare_digest(checks[name], check):
                raise unavailable()
            if name not in checks:
                db.add(PhoneCryptoKeyCheck(id=name, check_value=check))
        db.flush()
        return crypto

    def current_phone(self, user: User, crypto: PhoneCrypto) -> str | None:
        fields = (
            user.phone_ciphertext,
            user.phone_key_id,
            user.phone_lookup_hash,
            user.phone_verified_at,
        )
        if all(value is None for value in fields):
            return None
        if any(value is None for value in fields):
            raise unavailable()
        return crypto.decrypt(
            user.phone_ciphertext, user.phone_key_id, "user:" + user.id, user.phone_lookup_hash
        )

    def ready(self, db: Session) -> PhoneCrypto:
        settings = self.config()
        if not settings.enabled or not settings.provider_ready():
            raise unavailable()
        crypto = self.crypto(db)
        if self.provider is None:
            with self.init_lock:
                if self.provider is None:
                    self.provider = AliyunPhoneProvider(settings)
        return crypto

    def status(self, user_id: str, session_id: str) -> dict:
        with self.factory() as db:
            user = self.actor(db, user_id, session_id)
            result = dict(
                availability="unavailable",
                bound=user.phone_verified_at is not None,
                phone_masked=None,
                verified_at=user.phone_verified_at,
                revision=user.revision,
                retry_after=0,
                captcha=None,
            )
            latest = db.scalar(
                select(func.max(PhoneChallenge.created_at)).where(
                    PhoneChallenge.user_id == user_id,
                )
            )
            if latest:
                result["retry_after"] = max(
                    0, int((latest + timedelta(seconds=60) - utc_now()).total_seconds()) + 1
                )
        try:
            settings = self.config()
            if not settings.enabled and not result["bound"]:
                result["availability"] = "disabled"
                return result
            with self.transaction() as db:
                crypto = self.crypto(db)
                user = self.actor(db, user_id, session_id)
                result.update(
                    bound=user.phone_verified_at is not None,
                    verified_at=user.phone_verified_at,
                    revision=user.revision,
                )
                phone = self.current_phone(user, crypto)
                if phone:
                    result["phone_masked"] = phone[3:6] + "****" + phone[-4:]
                result["availability"] = "disabled" if not settings.enabled else "unavailable"
                if settings.enabled:
                    # Local reads do not depend on provider readiness.
                    try:
                        self.ready(db)
                    except Exception:
                        result["availability"] = "unavailable"
                    else:
                        result["availability"] = "ready"
                        result["captcha"] = dict(
                            region="cn",
                            prefix=settings.captcha_prefix,
                            scene_id=settings.captcha_scene_id,
                        )
        except Exception:
            result["availability"] = "unavailable"
            result["phone_masked"] = None
        return result

    def recover(self, db: Session) -> None:
        now = utc_now()
        for row in db.scalars(
            select(PhoneChallenge).where(
                PhoneChallenge.state.in_(["sending", "verifying"]),
                PhoneChallenge.operation_until <= now,
            )
        ):
            row.state = "invalid"
        # Bounded cleanup only beyond the entire rolling quota window.
        stale = list(
            db.scalars(
                select(PhoneChallenge.id)
                .where(
                    PhoneChallenge.created_at < now - timedelta(days=2),
                )
                .limit(100)
            )
        )
        if stale:
            db.execute(delete(PhoneChallenge).where(PhoneChallenge.id.in_(stale)))
        db.flush()

    def no_inflight(self, db: Session, user_id: str, phone_hash: str) -> None:
        if db.scalar(
            select(PhoneChallenge.id)
            .where(
                or_(
                    PhoneChallenge.user_id == user_id,
                    PhoneChallenge.phone_lookup_hash == phone_hash,
                ),
                PhoneChallenge.state.in_(["sending", "verifying"]),
            )
            .limit(1)
        ):
            raise conflict("有手机号认证正在处理，请稍后重试")

    def quota(self, db: Session, user_id: str, phone_hash: str) -> None:
        settings = self.config()
        now = utc_now()
        user_filter = PhoneChallenge.user_id == user_id
        number_filter = PhoneChallenge.phone_lookup_hash == phone_hash
        latest = db.scalar(
            select(func.max(PhoneChallenge.created_at)).where(
                or_(user_filter, number_filter),
            )
        )
        if latest and latest + timedelta(seconds=60) > now:
            raise AppError(
                "PHONE_RATE_LIMITED",
                "请稍后再发送验证码",
                status_code=429,
                details={
                    "retry_after": int((latest + timedelta(seconds=60) - now).total_seconds()) + 1
                },
            )
        for condition, hour_limit, day_limit in (
            (user_filter, settings.user_hour_limit, settings.user_day_limit),
            (number_filter, settings.number_hour_limit, settings.number_day_limit),
            (True, settings.global_hour_limit, settings.global_day_limit),
        ):
            for seconds, limit in ((3600, hour_limit), (86400, day_limit)):
                count = db.scalar(
                    select(func.count())
                    .select_from(PhoneChallenge)
                    .where(
                        condition,
                        PhoneChallenge.created_at >= now - timedelta(seconds=seconds),
                    )
                )
                if count >= limit:
                    raise AppError(
                        "PHONE_RATE_LIMITED", "短信发送次数已达上限，请稍后再试", status_code=429
                    )

    def send(self, user_id: str, session_id: str, number: str, token: str) -> dict:
        phone = normalize_phone(number)
        challenge_id = new_id()
        with self.transaction() as db:
            crypto = self.ready(db)
            user = self.actor(db, user_id, session_id)
            self.current_phone(user, crypto)
            phone_hash = crypto.fingerprint(phone)
            if db.scalar(select(User.id).where(User.phone_lookup_hash == phone_hash).limit(1)):
                raise conflict("该号码暂不可用于绑定")
            self.recover(db)
            self.no_inflight(db, user_id, phone_hash)
            self.quota(db, user_id, phone_hash)
            for old in db.scalars(
                select(PhoneChallenge).where(
                    or_(
                        PhoneChallenge.user_id == user_id,
                        PhoneChallenge.phone_lookup_hash == phone_hash,
                    ),
                    PhoneChallenge.state == "pending",
                )
            ):
                old.state = "invalid"
            ciphertext, key_id = crypto.encrypt(phone, "challenge:" + user_id + ":" + challenge_id)
            now = utc_now()
            db.add(
                PhoneChallenge(
                    id=challenge_id,
                    user_id=user_id,
                    session_id=session_id,
                    phone_ciphertext=ciphertext,
                    phone_key_id=key_id,
                    phone_lookup_hash=phone_hash,
                    original_phone_hash=user.phone_lookup_hash,
                    state="sending",
                    attempts=0,
                    created_at=now,
                    expires_at=now + timedelta(seconds=300),
                    operation_until=now + timedelta(seconds=30),
                )
            )
        try:
            if not self.provider.verify_captcha(token):
                raise AppError("PHONE_CAPTCHA_REJECTED", "图形验证未通过，请重新验证")
            # Recheck authorization/lease before the paid external operation.
            with self.transaction() as db:
                self.actor(db, user_id, session_id)
                row = db.get(PhoneChallenge, challenge_id)
                self.live_operation(row, "sending")
            self.provider.send(phone, challenge_id)
            with self.transaction() as db:
                user = self.actor(db, user_id, session_id)
                row = db.get(PhoneChallenge, challenge_id)
                self.live_operation(row, "sending")
                if user.phone_lookup_hash != row.original_phone_hash:
                    raise conflict()
                row.state = "pending"
                result = dict(challenge_id=row.id, expires_at=row.expires_at, retry_after=60)
            return result
        except Exception:
            self.invalidate(challenge_id, "sending")
            raise

    def live_operation(self, row: PhoneChallenge | None, state: str) -> None:
        if not row or row.state != state or row.operation_until <= utc_now():
            raise conflict("认证已失效，请重新发送验证码")

    def invalidate(self, challenge_id: str, state: str) -> None:
        with self.transaction() as db:
            row = db.get(PhoneChallenge, challenge_id)
            if row and row.state == state:
                row.state = "invalid"

    def verify(
        self,
        user_id: str,
        session_id: str,
        challenge_id: str,
        code: str,
        revision: int,
        password: str | None,
        request_id: str,
    ) -> dict:
        error = None
        completed = False
        with self.transaction() as db:
            crypto = self.ready(db)
            user = self.actor(db, user_id, session_id)
            self.current_phone(user, crypto)
            self.recover(db)
            row = db.get(PhoneChallenge, challenge_id)
            if not row or row.user_id != user_id or row.session_id != session_id:
                raise AppError("PHONE_CHALLENGE_NOT_FOUND", "认证记录不存在", status_code=404)
            if row.state == "completed":
                completed = True
            else:
                if row.state != "pending" or row.expires_at <= utc_now() or row.attempts >= 5:
                    raise conflict("认证已失效，请重新发送验证码")
                if user.revision != revision or user.phone_lookup_hash != row.original_phone_hash:
                    raise conflict()
                self.no_inflight(db, user_id, row.phone_lookup_hash)
                phone = crypto.decrypt(
                    row.phone_ciphertext,
                    row.phone_key_id,
                    "challenge:" + user_id + ":" + row.id,
                    row.phone_lookup_hash,
                )
                row.attempts += 1
                row.state = "verifying"
                row.operation_until = utc_now() + timedelta(seconds=30)
                password_hash = user.password_hash if user.phone_lookup_hash else None
                starting_revision = user.revision
        if completed:
            return self.status(user_id, session_id)
        # Password hashing and all provider calls happen outside the database transaction.
        try:
            if password_hash and (not password or not verify_password(password_hash, password)):
                error = AppError("INVALID_CURRENT_PASSWORD", "当前密码错误")
                valid = False
            else:
                valid = self.provider.verify(phone, challenge_id, code)
                if not valid:
                    error = AppError("PHONE_CODE_INVALID", "短信验证码错误，请重新输入")
            with self.transaction() as db:
                self.crypto(db)
                user = self.actor(db, user_id, session_id)
                row = db.get(PhoneChallenge, challenge_id)
                self.live_operation(row, "verifying")
                if row.expires_at <= utc_now():
                    raise conflict("验证码已过期，请重新发送")
                if (
                    user.revision != starting_revision
                    or user.phone_lookup_hash != row.original_phone_hash
                ):
                    raise conflict()
                if not valid:
                    row.state = "invalid" if row.attempts >= 5 else "pending"
                else:
                    if db.scalar(
                        select(User.id)
                        .where(
                            User.phone_lookup_hash == row.phone_lookup_hash,
                            User.id != user_id,
                        )
                        .limit(1)
                    ):
                        raise conflict("该号码暂不可用于绑定")
                    action = (
                        "profile.phone.change" if user.phone_lookup_hash else "profile.phone.bind"
                    )
                    user.phone_ciphertext, user.phone_key_id = crypto.encrypt(
                        phone, "user:" + user_id
                    )
                    user.phone_lookup_hash = row.phone_lookup_hash
                    user.phone_verified_at = utc_now()
                    user.revision += 1
                    row.state = "completed"
                    record_audit(
                        db,
                        actor=user,
                        action=action,
                        entity_type="user",
                        entity_id=user.id,
                        request_id=request_id,
                    )
            if error:
                raise error
        except Exception:
            self.invalidate(challenge_id, "verifying")
            raise
        return self.status(user_id, session_id)
