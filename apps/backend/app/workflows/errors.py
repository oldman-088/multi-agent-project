"""Exceptions raised by the workflow orchestration engine."""

from __future__ import annotations

from collections.abc import Sequence


class WorkflowError(Exception):
    """Base class for every workflow-engine error."""


class DAGValidationError(WorkflowError, ValueError):
    """The task dependency graph is structurally invalid."""


class DAGCycleError(DAGValidationError):
    """The task dependency graph contains a cycle.

    Attributes:
        cycle: The cycle as a closed walk, e.g. ``("a", "b", "a")``.
    """

    def __init__(self, cycle: Sequence[str]) -> None:
        self.cycle: tuple[str, ...] = tuple(cycle)
        super().__init__("task dependency graph contains a cycle: " + " -> ".join(self.cycle))


class DuplicateTaskError(DAGValidationError):
    """Two tasks in the plan share the same task id."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"duplicate task id: {task_id!r}")


class UnknownDependencyError(DAGValidationError):
    """A task depends on a task id that does not exist in the plan."""

    def __init__(self, task_id: str, missing: str) -> None:
        self.task_id = task_id
        self.missing = missing
        super().__init__(f"task {task_id!r} depends on unknown task {missing!r}")


class LimitExceededError(WorkflowError, ValueError):
    """A hard limit is exceeded; hard caps can be lowered, never raised.

    Attributes:
        limit: Name of the limit, e.g. ``"max_workers"``.
        value: The offending value.
        ceiling: The absolute maximum for the limit.
    """

    def __init__(self, limit: str, value: object, ceiling: object) -> None:
        self.limit = limit
        self.value = value
        self.ceiling = ceiling
        super().__init__(f"hard limit {limit!r} exceeded: {value!r} > {ceiling!r}")


class ClaimError(WorkflowError):
    """Base class for atomic-claim errors."""


class ClaimConflictError(ClaimError):
    """The claim token does not hold the task (already released or taken)."""


class CircuitOpenError(WorkflowError):
    """The circuit breaker guarding this task kind is open; the call was not run."""
