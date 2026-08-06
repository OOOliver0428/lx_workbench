from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.errors import AppError


@dataclass
class _UserQuota:
    requests: deque[float] = field(default_factory=deque)
    token_day: str = ""
    consumed_tokens: int = 0
    reserved_tokens: int = 0
    active_generations: int = 0
    last_completed: dict[str, float] = field(default_factory=dict)


class GenerationLease:
    def __init__(self, reserved_tokens: int) -> None:
        self.reserved_tokens = reserved_tokens
        self.total_tokens: int | None = None
        self.day_key: str | None = None

    def record_usage(self, usage: dict[str, Any] | None) -> None:
        if usage is None:
            return
        total = usage.get("total_tokens")
        if isinstance(total, int) and total >= 0:
            self.total_tokens = total


class LLMGuard:
    def __init__(
        self,
        *,
        max_concurrent: int = 2,
        max_user_concurrent: int = 1,
        user_requests_per_hour: int = 20,
        user_tokens_per_day: int = 100_000,
        global_tokens_per_day: int = 1_000_000,
        max_tracked_users: int = 10_000,
        cooldown_seconds: dict[str, int] | None = None,
    ) -> None:
        self.max_user_concurrent = max_user_concurrent
        self.user_requests_per_hour = user_requests_per_hour
        self.user_tokens_per_day = user_tokens_per_day
        self.global_tokens_per_day = global_tokens_per_day
        self.max_tracked_users = max_tracked_users
        self.cooldown_seconds = cooldown_seconds or {}
        self._users: OrderedDict[str, _UserQuota] = OrderedDict()
        self._inflight_keys: set[str] = set()
        self._global_token_day = ""
        self._global_consumed_tokens = 0
        self._global_reserved_tokens = 0
        self._semaphore = threading.BoundedSemaphore(max_concurrent)
        self._lock = threading.Lock()

    @staticmethod
    def _day_key() -> str:
        return datetime.now(UTC).date().isoformat()

    @staticmethod
    def _prune_requests(requests: deque[float], now: float) -> None:
        while requests and now - requests[0] > 3600:
            requests.popleft()

    def _user_quota(self, user_id: str, day_key: str) -> _UserQuota:
        quota = self._users.get(user_id)
        if quota is None:
            if len(self._users) >= self.max_tracked_users:
                for candidate_id, candidate in self._users.items():
                    if candidate.active_generations == 0:
                        self._users.pop(candidate_id)
                        break
                else:
                    raise AppError(
                        "AI_CAPACITY_EXCEEDED",
                        "AI 服务当前繁忙，请稍后重试",
                        status_code=429,
                    )
            quota = _UserQuota()
            self._users[user_id] = quota
        else:
            self._users.move_to_end(user_id)
        if quota.token_day != day_key:
            quota.token_day = day_key
            quota.consumed_tokens = 0
            quota.reserved_tokens = 0
        return quota

    def _reset_global_day(self, day_key: str) -> None:
        if self._global_token_day == day_key:
            return
        self._global_token_day = day_key
        self._global_consumed_tokens = 0
        self._global_reserved_tokens = 0

    @contextmanager
    def generation(
        self,
        *,
        user_id: str,
        purpose: str,
        max_tokens: int,
        idempotency_key: str,
    ) -> Iterator[GenerationLease]:
        if not self._semaphore.acquire(blocking=False):
            raise AppError(
                "AI_CAPACITY_EXCEEDED",
                "AI 服务当前繁忙，请稍后重试",
                status_code=429,
            )

        started = False
        lease = GenerationLease(max_tokens)
        try:
            now = time.monotonic()
            day_key = self._day_key()
            with self._lock:
                quota = self._user_quota(user_id, day_key)
                self._reset_global_day(day_key)
                self._prune_requests(quota.requests, now)
                cooldown = self.cooldown_seconds.get(purpose, 0)
                if now - quota.last_completed.get(purpose, -float("inf")) < cooldown:
                    raise AppError(
                        "AI_GENERATION_COOLDOWN",
                        "该 AI 操作刚刚完成，请稍后再试",
                        status_code=429,
                    )
                if idempotency_key in self._inflight_keys:
                    raise AppError(
                        "AI_GENERATION_IN_PROGRESS",
                        "相同 AI 请求正在处理中",
                        status_code=409,
                    )
                if quota.active_generations >= self.max_user_concurrent:
                    raise AppError(
                        "AI_USER_CAPACITY_EXCEEDED",
                        "当前账号已有 AI 请求正在处理中",
                        status_code=429,
                    )
                if len(quota.requests) >= self.user_requests_per_hour:
                    raise AppError(
                        "AI_REQUEST_QUOTA_EXCEEDED",
                        "当前账号本小时 AI 请求额度已用完",
                        status_code=429,
                    )
                if (
                    quota.consumed_tokens + quota.reserved_tokens + max_tokens
                    > self.user_tokens_per_day
                ):
                    raise AppError(
                        "AI_TOKEN_QUOTA_EXCEEDED",
                        "当前账号今日 AI token 额度已用完",
                        status_code=429,
                    )
                if (
                    self._global_consumed_tokens
                    + self._global_reserved_tokens
                    + max_tokens
                    > self.global_tokens_per_day
                ):
                    raise AppError(
                        "AI_GLOBAL_TOKEN_QUOTA_EXCEEDED",
                        "系统今日 AI token 额度已用完",
                        status_code=429,
                    )
                quota.requests.append(now)
                quota.reserved_tokens += max_tokens
                quota.active_generations += 1
                self._global_reserved_tokens += max_tokens
                self._inflight_keys.add(idempotency_key)
                lease.day_key = day_key
                started = True

            yield lease
        except Exception:
            if started:
                self._finish(
                    user_id=user_id,
                    purpose=purpose,
                    idempotency_key=idempotency_key,
                    lease=lease,
                    succeeded=False,
                )
            raise
        else:
            self._finish(
                user_id=user_id,
                purpose=purpose,
                idempotency_key=idempotency_key,
                lease=lease,
                succeeded=True,
            )
        finally:
            self._semaphore.release()

    def _finish(
        self,
        *,
        user_id: str,
        purpose: str,
        idempotency_key: str,
        lease: GenerationLease,
        succeeded: bool,
    ) -> None:
        with self._lock:
            quota = self._users[user_id]
            same_user_day = quota.token_day == lease.day_key
            same_global_day = self._global_token_day == lease.day_key
            if same_user_day:
                quota.reserved_tokens = max(
                    0, quota.reserved_tokens - lease.reserved_tokens
                )
            quota.active_generations -= 1
            if same_global_day:
                self._global_reserved_tokens = max(
                    0, self._global_reserved_tokens - lease.reserved_tokens
                )
            self._inflight_keys.discard(idempotency_key)
            if succeeded:
                used = lease.total_tokens
                if used is None:
                    used = lease.reserved_tokens
                if same_user_day:
                    quota.consumed_tokens += used
                if same_global_day:
                    self._global_consumed_tokens += used
                quota.last_completed[purpose] = time.monotonic()
