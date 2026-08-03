from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class LoginThrottle:
    def __init__(self, *, max_failures: int = 5, window_seconds: int = 300) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> None:
        failures = self._failures[key]
        while failures and now - failures[0] > self.window_seconds:
            failures.popleft()
        if not failures:
            self._failures.pop(key, None)

    def is_blocked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            self._prune(key, now)
            return len(self._failures.get(key, ())) >= self.max_failures

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(key, now)
            self._failures[key].append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    @staticmethod
    def _login_keys(client_ip: str, login_identifier: str) -> tuple[str, str]:
        return (
            f"source-login:{client_ip}:{login_identifier}",
            f"login:{login_identifier}",
        )

    def is_login_blocked(self, client_ip: str, login_identifier: str) -> bool:
        return any(
            self.is_blocked(key)
            for key in self._login_keys(client_ip, login_identifier)
        )

    def record_login_failure(self, client_ip: str, login_identifier: str) -> None:
        for key in self._login_keys(client_ip, login_identifier):
            self.record_failure(key)

    def clear_login(self, client_ip: str, login_identifier: str) -> None:
        for key in self._login_keys(client_ip, login_identifier):
            self.clear(key)
