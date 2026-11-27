"""Tests for hard limits and the retry policy (hard caps cannot be raised)."""

from __future__ import annotations

import pytest

from app.workflows.errors import LimitExceededError
from app.workflows.limits import (
    ABSOLUTE_MAX_ATTEMPTS,
    ABSOLUTE_MAX_SECONDS,
    ABSOLUTE_MAX_STEPS,
    ABSOLUTE_MAX_TASKS,
    ABSOLUTE_MAX_WORKERS,
    HardLimits,
    RetryPolicy,
)


class TestHardLimits:
    def test_defaults_are_valid(self) -> None:
        limits = HardLimits()
        assert limits.max_workers == 4
        assert limits.max_tasks == 64
        assert limits.max_steps == 256

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("max_workers", 0),
            ("max_workers", -1),
            ("max_tasks", 0),
            ("max_steps", 0),
        ],
    )
    def test_rejects_non_positive_values(self, field: str, value: int) -> None:
        with pytest.raises(ValueError):
            HardLimits(**{field: value})

    def test_rejects_zero_seconds(self) -> None:
        with pytest.raises(ValueError):
            HardLimits(max_seconds=0.0)

    @pytest.mark.parametrize(
        ("field", "value", "ceiling"),
        [
            ("max_workers", ABSOLUTE_MAX_WORKERS + 1, ABSOLUTE_MAX_WORKERS),
            ("max_tasks", ABSOLUTE_MAX_TASKS + 1, ABSOLUTE_MAX_TASKS),
            ("max_seconds", ABSOLUTE_MAX_SECONDS + 1.0, ABSOLUTE_MAX_SECONDS),
            ("max_steps", ABSOLUTE_MAX_STEPS + 1, ABSOLUTE_MAX_STEPS),
        ],
    )
    def test_absolute_caps_are_hard(self, field: str, value: object, ceiling: object) -> None:
        with pytest.raises(LimitExceededError) as excinfo:
            HardLimits(**{field: value})
        assert excinfo.value.limit == field
        assert excinfo.value.ceiling == ceiling

    def test_caps_allow_the_maximum(self) -> None:
        limits = HardLimits(
            max_workers=ABSOLUTE_MAX_WORKERS,
            max_tasks=ABSOLUTE_MAX_TASKS,
            max_seconds=ABSOLUTE_MAX_SECONDS,
            max_steps=ABSOLUTE_MAX_STEPS,
        )
        assert limits.max_workers == ABSOLUTE_MAX_WORKERS

    @pytest.mark.parametrize("field", ["max_workers", "max_tasks", "max_steps"])
    def test_rejects_non_int(self, field: str) -> None:
        with pytest.raises(ValueError):
            HardLimits(**{field: 2.5})  # type: ignore[arg-type]

    def test_limits_are_immutable(self) -> None:
        limits = HardLimits()
        with pytest.raises(AttributeError):
            limits.max_workers = 99  # type: ignore[misc]


class TestRetryPolicy:
    def test_defaults(self) -> None:
        policy = RetryPolicy()
        assert policy.max_attempts == 3

    def test_rejects_zero_attempts(self) -> None:
        with pytest.raises(ValueError):
            RetryPolicy(max_attempts=0)

    def test_attempts_are_capped(self) -> None:
        with pytest.raises(LimitExceededError):
            RetryPolicy(max_attempts=ABSOLUTE_MAX_ATTEMPTS + 1)

    def test_rejects_negative_backoff(self) -> None:
        with pytest.raises(ValueError):
            RetryPolicy(backoff_seconds=-1.0)

    def test_rejects_backoff_multiplier_below_one(self) -> None:
        with pytest.raises(ValueError):
            RetryPolicy(backoff_multiplier=0.5)

    def test_exponential_delays(self) -> None:
        policy = RetryPolicy(max_attempts=4, backoff_seconds=1.0, backoff_multiplier=2.0)
        assert policy.delay_before_retry(1) == 1.0
        assert policy.delay_before_retry(2) == 2.0
        assert policy.delay_before_retry(3) == 4.0

    def test_rejects_bad_attempt_number(self) -> None:
        with pytest.raises(ValueError):
            RetryPolicy().delay_before_retry(0)
