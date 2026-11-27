"""Hard limits and the retry policy for workflow runs.

docs/SPEC.md (Phase 3, workforce engine) requires "hard caps on workers,
concurrency, time and steps".  :class:`HardLimits` models those caps: a run may
lower them, never raise them past the absolute ceilings below, and the
scheduler enforces every one of them while running (see
``app.workflows.scheduler``).  The absolute ceilings are module constants on
purpose — there is no configuration knob that disables them.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import LimitExceededError

# Absolute hard ceilings. Configuration may pick smaller values, never larger.
ABSOLUTE_MAX_WORKERS = 32
ABSOLUTE_MAX_TASKS = 1_024
ABSOLUTE_MAX_SECONDS = 3_600.0
ABSOLUTE_MAX_STEPS = 10_000
ABSOLUTE_MAX_ATTEMPTS = 16


def _check_int(name: str, value: int, ceiling: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int, got {type(value).__name__}")
    if value < 1:
        raise ValueError(f"{name} must be >= 1, got {value}")
    if value > ceiling:
        raise LimitExceededError(name, value, ceiling)


def _check_float(name: str, value: float, ceiling: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, got {type(value).__name__}")
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}")
    if value > ceiling:
        raise LimitExceededError(name, value, ceiling)


@dataclass(frozen=True, slots=True)
class HardLimits:
    """Hard caps for one workflow run.

    Attributes:
        max_workers: Maximum number of worker slots (== maximum concurrent
            task executions).  Capped at :data:`ABSOLUTE_MAX_WORKERS`.
        max_tasks: Maximum number of tasks in a run, counting original tasks
            and any replan additions.  Capped at :data:`ABSOLUTE_MAX_TASKS`.
        max_seconds: Wall-clock budget for the run.  Capped at
            :data:`ABSOLUTE_MAX_SECONDS`.
        max_steps: Maximum scheduling steps — every dispatched attempt and
            every replan consumes one step.  Capped at
            :data:`ABSOLUTE_MAX_STEPS`.
    """

    max_workers: int = 4
    max_tasks: int = 64
    max_seconds: float = 300.0
    max_steps: int = 256

    def __post_init__(self) -> None:
        _check_int("max_workers", self.max_workers, ABSOLUTE_MAX_WORKERS)
        _check_int("max_tasks", self.max_tasks, ABSOLUTE_MAX_TASKS)
        _check_float("max_seconds", self.max_seconds, ABSOLUTE_MAX_SECONDS)
        _check_int("max_steps", self.max_steps, ABSOLUTE_MAX_STEPS)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How often a failed task is retried before the failure is permanent.

    Attributes:
        max_attempts: Total attempts per task (>= 1).  A per-task
            ``TaskSpec.max_attempts`` overrides this.  Capped at
            :data:`ABSOLUTE_MAX_ATTEMPTS`.
        backoff_seconds: Sleep before the second attempt.
        backoff_multiplier: Exponential factor applied per further attempt.
    """

    max_attempts: int = 3
    backoff_seconds: float = 0.0
    backoff_multiplier: float = 2.0

    def __post_init__(self) -> None:
        _check_int("max_attempts", self.max_attempts, ABSOLUTE_MAX_ATTEMPTS)
        _check_float("backoff_multiplier", self.backoff_multiplier, 1_000.0)
        if self.backoff_multiplier < 1:
            raise ValueError(f"backoff_multiplier must be >= 1, got {self.backoff_multiplier}")
        if isinstance(self.backoff_seconds, bool) or not isinstance(
            self.backoff_seconds, (int, float)
        ):
            raise ValueError(
                f"backoff_seconds must be a number, got {type(self.backoff_seconds).__name__}"
            )
        if self.backoff_seconds < 0:
            raise ValueError(f"backoff_seconds must be >= 0, got {self.backoff_seconds}")
        if self.backoff_seconds > ABSOLUTE_MAX_SECONDS:
            raise LimitExceededError("backoff_seconds", self.backoff_seconds, ABSOLUTE_MAX_SECONDS)

    def delay_before_retry(self, failed_attempt: int) -> float:
        """Seconds to sleep after attempt ``failed_attempt`` (1-based) failed."""
        if failed_attempt < 1:
            raise ValueError(f"failed_attempt must be >= 1, got {failed_attempt}")
        return self.backoff_seconds * (self.backoff_multiplier ** (failed_attempt - 1))
