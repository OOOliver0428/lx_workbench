from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


class LoginCapacityExceeded(Exception):
    pass


@dataclass(frozen=True)
class LoginFailureDecision:
    should_audit: bool
    failure_count: int
    suppressed_audits: int


class LoginThrottle:
    def __init__(
        self,
        *,
        max_verifications: int = 120,
        max_source_verifications: int = 60,
        window_seconds: int = 60,
        max_concurrent: int = 2,
        max_keys: int = 2048,
        audit_limit: int = 20,
        failure_window_seconds: int = 300,
    ) -> None:
        self.max_verifications = max_verifications
        self.max_source_verifications = max_source_verifications
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self.audit_limit = audit_limit
        self.failure_window_seconds = failure_window_seconds
        self._verification_attempts: deque[float] = deque()
        self._source_attempts: OrderedDict[str, deque[float]] = OrderedDict()
        self._login_failures: OrderedDict[str, deque[float]] = OrderedDict()
        self._audit_events: deque[float] = deque()
        self._suppressed_audits = 0
        self._semaphore = threading.BoundedSemaphore(max_concurrent)
        self._lock = threading.Lock()

    @staticmethod
    def _prune_window(events: deque[float], now: float, window_seconds: int) -> None:
        while events and now - events[0] > window_seconds:
            events.popleft()

    def _prune_map(
        self,
        entries: OrderedDict[str, deque[float]],
        now: float,
        window_seconds: int,
    ) -> None:
        expired: list[str] = []
        for key, events in entries.items():
            self._prune_window(events, now, window_seconds)
            if not events:
                expired.append(key)
        for key in expired:
            entries.pop(key, None)

    def _events_for(
        self,
        entries: OrderedDict[str, deque[float]],
        key: str,
    ) -> deque[float]:
        events = entries.get(key)
        if events is None:
            if len(entries) >= self.max_keys:
                entries.popitem(last=False)
            events = deque()
            entries[key] = events
        else:
            entries.move_to_end(key)
        return events

    @contextmanager
    def verification_slot(self, client_ip: str) -> Iterator[None]:
        now = time.monotonic()
        with self._lock:
            self._prune_window(self._verification_attempts, now, self.window_seconds)
            self._prune_map(self._source_attempts, now, self.window_seconds)
            source_attempts = self._events_for(self._source_attempts, client_ip)
            if (
                len(self._verification_attempts) >= self.max_verifications
                or len(source_attempts) >= self.max_source_verifications
            ):
                raise LoginCapacityExceeded
            self._verification_attempts.append(now)
            source_attempts.append(now)

        if not self._semaphore.acquire(blocking=False):
            raise LoginCapacityExceeded
        try:
            yield
        finally:
            self._semaphore.release()

    def record_login_failure(
        self,
        client_ip: str,
        login_identifier: str,
    ) -> LoginFailureDecision:
        del client_ip  # Source-level protection is applied before password verification.
        now = time.monotonic()
        with self._lock:
            self._prune_map(
                self._login_failures,
                now,
                self.failure_window_seconds,
            )
            failures = self._events_for(self._login_failures, login_identifier)
            failures.append(now)
            failure_count = len(failures)

            self._prune_window(self._audit_events, now, self.window_seconds)
            sampled = failure_count in {1, 5, 10} or failure_count % 25 == 0
            should_audit = sampled and len(self._audit_events) < self.audit_limit
            if should_audit:
                self._audit_events.append(now)
                suppressed = self._suppressed_audits
                self._suppressed_audits = 0
            else:
                self._suppressed_audits += 1
                suppressed = 0
            return LoginFailureDecision(
                should_audit=should_audit,
                failure_count=failure_count,
                suppressed_audits=suppressed,
            )

    def clear_login(self, client_ip: str, login_identifier: str) -> None:
        del client_ip
        with self._lock:
            self._login_failures.pop(login_identifier, None)

    @property
    def tracked_key_count(self) -> int:
        with self._lock:
            return len(self._source_attempts) + len(self._login_failures)
