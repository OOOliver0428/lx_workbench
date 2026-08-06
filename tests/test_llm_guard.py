from __future__ import annotations

import pytest

from app.errors import AppError
from app.llm_guard import LLMGuard


def test_llm_guard_rejects_concurrent_work() -> None:
    guard = LLMGuard(max_concurrent=1)

    with (
        guard.generation(
            user_id="user-1",
            purpose="chat",
            max_tokens=100,
            idempotency_key="chat:user-1:first",
        ),
        pytest.raises(AppError) as caught,
        guard.generation(
            user_id="user-2",
            purpose="chat",
            max_tokens=100,
            idempotency_key="chat:user-2:second",
        ),
    ):
        pass

    assert caught.value.code == "AI_CAPACITY_EXCEEDED"


def test_llm_guard_accounts_actual_usage_and_reserves_future_budget() -> None:
    guard = LLMGuard(
        user_tokens_per_day=100,
        global_tokens_per_day=200,
        cooldown_seconds={"chat": 0},
    )
    with guard.generation(
        user_id="user-1",
        purpose="chat",
        max_tokens=80,
        idempotency_key="chat:user-1:first",
    ) as lease:
        lease.record_usage({"total_tokens": 60})

    with pytest.raises(AppError) as caught, guard.generation(
        user_id="user-1",
        purpose="chat",
        max_tokens=50,
        idempotency_key="chat:user-1:second",
    ):
        pass

    assert caught.value.code == "AI_TOKEN_QUOTA_EXCEEDED"


def test_llm_guard_does_not_corrupt_reservations_across_day_rollover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    day = ["2026-08-06"]
    monkeypatch.setattr(LLMGuard, "_day_key", staticmethod(lambda: day[0]))
    guard = LLMGuard(
        max_concurrent=2,
        max_user_concurrent=2,
        cooldown_seconds={"chat": 0, "weekly": 0},
    )

    with guard.generation(
        user_id="user-1",
        purpose="chat",
        max_tokens=100,
        idempotency_key="chat:user-1:first",
    ):
        day[0] = "2026-08-07"
        with guard.generation(
            user_id="user-1",
            purpose="weekly",
            max_tokens=50,
            idempotency_key="weekly:user-1:first",
        ):
            pass

    quota = guard._users["user-1"]
    assert quota.token_day == "2026-08-07"
    assert quota.reserved_tokens == 0
    assert quota.consumed_tokens == 50
    assert guard._global_reserved_tokens == 0
    assert guard._global_consumed_tokens == 50
