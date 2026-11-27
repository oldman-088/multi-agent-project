"""Status vocabularies for workflow tasks and whole runs."""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    """Lifecycle of a single task (also the vocabulary of the durable store)."""

    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED)


class RunStatus(StrEnum):
    """Outcome of a whole workflow run.

    - ``COMPLETED``: every task finished and no failure was left unrecovered
      (a task that failed after its replan replacements succeeded counts as
      recovered — see ``RunReport.replans``).
    - ``FAILED``: at least one task failed permanently (or was cancelled
      because a dependency did not succeed) and was not recovered by a replan.
    - ``TIMED_OUT``: the ``max_seconds`` hard limit stopped the run while
      tasks were still unfinished.
    - ``STEP_LIMIT_REACHED``: the ``max_steps`` hard limit stopped the run
      while tasks were still unfinished.
    """

    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    STEP_LIMIT_REACHED = "step_limit_reached"
