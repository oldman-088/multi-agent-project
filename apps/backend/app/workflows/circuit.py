"""Circuit breaker guarding task execution.

docs/SPEC.md (Phase 3) pairs retries and replanning with resilience checks;
the breaker wraps an execution call ("wrapped circuit check"): after
``failure_threshold`` failures the circuit opens and calls fail fast with
:class:`~app.workflows.errors.CircuitOpenError` without touching the executor,
until ``reset_timeout`` elapses and one half-open trial succeeds.

The class is thread-safe and takes an injectable ``clock`` so tests do not
sleep.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from enum import StrEnum
from typing import TypeVar

from .errors import CircuitOpenError

_T = TypeVar("_T")


class CircuitState(StrEnum):
    """State of a circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Classic three-state circuit breaker around a callable."""

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        reset_timeout: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(failure_threshold, bool) or not isinstance(failure_threshold, int):
            raise ValueError("failure_threshold must be an int")
        if failure_threshold < 1:
            raise ValueError(f"failure_threshold must be >= 1, got {failure_threshold}")
        if reset_timeout <= 0:
            raise ValueError(f"reset_timeout must be > 0, got {reset_timeout}")
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._state = CircuitState.CLOSED
        self._opened_at = 0.0
        self._trial_in_flight = False

    @property
    def state(self) -> CircuitState:
        """Current state, transitioning OPEN -> HALF_OPEN when the timeout passed."""
        with self._lock:
            self._refresh_locked()
            return self._state

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failures

    def _refresh_locked(self) -> None:
        elapsed = self._clock() - self._opened_at
        if self._state is CircuitState.OPEN and elapsed >= self.reset_timeout:
            self._state = CircuitState.HALF_OPEN
            self._trial_in_flight = False

    def allow(self) -> bool:
        """Whether a call may proceed right now.

        In the HALF_OPEN state exactly one trial call is allowed; it must be
        followed by :meth:`record_success` or :meth:`record_failure`.
        """
        with self._lock:
            self._refresh_locked()
            if self._state is CircuitState.CLOSED:
                return True
            if self._state is CircuitState.HALF_OPEN and not self._trial_in_flight:
                self._trial_in_flight = True
                return True
            return False

    def record_success(self) -> None:
        """Record a successful call: the circuit closes."""
        with self._lock:
            self._failures = 0
            self._state = CircuitState.CLOSED
            self._trial_in_flight = False

    def record_failure(self) -> None:
        """Record a failed call: opens the circuit at the threshold."""
        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._trip_locked()
                return
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._trip_locked()

    def _trip_locked(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self._clock()
        self._trial_in_flight = False

    def call(self, fn: Callable[..., _T], *args: object, **kwargs: object) -> _T:
        """Run ``fn`` under the breaker; raises CircuitOpenError when open."""
        if not self.allow():
            raise CircuitOpenError(
                f"circuit is open after {self.failure_threshold} failures; "
                f"retry after {self.reset_timeout}s"
            )
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result
