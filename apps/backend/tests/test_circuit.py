"""Tests for the circuit breaker (wrapped circuit checks around execution)."""

from __future__ import annotations

import pytest

from app.workflows.circuit import CircuitBreaker, CircuitState
from app.workflows.errors import CircuitOpenError


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def boom() -> None:
    raise RuntimeError("boom")


class TestCircuitBreaker:
    def test_starts_closed_and_passes_calls(self) -> None:
        breaker = CircuitBreaker(failure_threshold=2, reset_timeout=10.0)
        assert breaker.state is CircuitState.CLOSED
        assert breaker.call(lambda: 42) == 42
        assert breaker.state is CircuitState.CLOSED

    def test_opens_after_threshold_failures(self) -> None:
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=2, reset_timeout=10.0, clock=clock)
        with pytest.raises(RuntimeError):
            breaker.call(boom)
        assert breaker.state is CircuitState.CLOSED
        with pytest.raises(RuntimeError):
            breaker.call(boom)
        assert breaker.state is CircuitState.OPEN

    def test_open_circuit_fails_fast_without_calling(self) -> None:
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, reset_timeout=10.0, clock=clock)
        with pytest.raises(RuntimeError):
            breaker.call(boom)
        calls = []

        def guarded() -> str:
            calls.append(1)
            return "ran"

        with pytest.raises(CircuitOpenError):
            breaker.call(guarded)
        assert calls == []  # the wrapped call never executed

    def test_half_open_after_reset_timeout(self) -> None:
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, reset_timeout=10.0, clock=clock)
        with pytest.raises(RuntimeError):
            breaker.call(boom)
        assert breaker.state is CircuitState.OPEN
        clock.advance(9.9)
        assert breaker.state is CircuitState.OPEN
        clock.advance(0.2)
        assert breaker.state is CircuitState.HALF_OPEN

    def test_half_open_allows_one_trial_then_rejects(self) -> None:
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, reset_timeout=10.0, clock=clock)
        with pytest.raises(RuntimeError):
            breaker.call(boom)
        clock.advance(11.0)
        calls = []

        def trial() -> str:
            calls.append(1)
            return "ok"

        assert breaker.call(trial) == "ok"  # the single trial
        assert calls == [1]
        assert breaker.state is CircuitState.CLOSED

    def test_half_open_trial_failure_reopens(self) -> None:
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, reset_timeout=10.0, clock=clock)
        with pytest.raises(RuntimeError):
            breaker.call(boom)
        clock.advance(11.0)
        with pytest.raises(RuntimeError):
            breaker.call(boom)  # half-open trial fails
        assert breaker.state is CircuitState.OPEN
        with pytest.raises(CircuitOpenError):
            breaker.call(boom)

    def test_success_resets_failure_count(self) -> None:
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=3, reset_timeout=10.0, clock=clock)
        with pytest.raises(RuntimeError):
            breaker.call(boom)
        with pytest.raises(RuntimeError):
            breaker.call(boom)
        assert breaker.call(lambda: "fine") == "fine"
        assert breaker.failure_count == 0
        with pytest.raises(RuntimeError):
            breaker.call(boom)
        assert breaker.state is CircuitState.CLOSED  # threshold restarted

    def test_allow_records_half_open_trial(self) -> None:
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, reset_timeout=5.0, clock=clock)
        breaker.record_failure()
        clock.advance(6.0)
        assert breaker.allow() is True  # takes the trial slot
        assert breaker.allow() is False  # trial already taken

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"failure_threshold": 0}, "failure_threshold"),
            ({"reset_timeout": 0.0}, "reset_timeout"),
        ],
    )
    def test_rejects_invalid_configuration(self, kwargs: dict[str, object], message: str) -> None:
        with pytest.raises(ValueError, match=message):
            CircuitBreaker(**kwargs)  # type: ignore[arg-type]
