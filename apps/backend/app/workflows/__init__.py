"""Workflow orchestration engine (docs/SPEC.md Phase 3 workforce engine).

Public surface:

- :func:`~app.workflows.dag.validate_dag` — reject plans with dependency cycles.
- :func:`~app.workflows.claims.claim_task` — atomic task claim (SQLite + PostgreSQL).
- :func:`~app.workflows.scheduler.run_workflow` — bounded parallel scheduling
  with retries, replanning on repeated failure and hard limits.
- :class:`~app.workflows.limits.HardLimits` / :class:`~app.workflows.limits.RetryPolicy`.
- :class:`~app.workflows.circuit.CircuitBreaker` — wrapped circuit checks around
  task execution.
- :class:`~app.workflows.store.SqlAlchemyTaskStore` — durable claims store.
"""

from .circuit import CircuitBreaker, CircuitState
from .claims import Claim, claim_task, complete_claim, release_claim
from .dag import TaskSpec, find_cycle, ready_tasks, validate_dag
from .errors import (
    CircuitOpenError,
    ClaimConflictError,
    ClaimError,
    DAGCycleError,
    DAGValidationError,
    DuplicateTaskError,
    LimitExceededError,
    UnknownDependencyError,
    WorkflowError,
)
from .limits import HardLimits, RetryPolicy
from .models import Base, WorkflowTaskRecord
from .scheduler import ReplanContext, RunReport, TaskOutcome, run_workflow
from .status import RunStatus, TaskStatus
from .store import SqlAlchemyTaskStore, TaskStore

__all__ = [
    "Base",
    "CircuitBreaker",
    "CircuitOpenError",
    "CircuitState",
    "Claim",
    "ClaimConflictError",
    "ClaimError",
    "DAGCycleError",
    "DAGValidationError",
    "DuplicateTaskError",
    "HardLimits",
    "LimitExceededError",
    "ReplanContext",
    "RetryPolicy",
    "RunReport",
    "RunStatus",
    "SqlAlchemyTaskStore",
    "TaskOutcome",
    "TaskSpec",
    "TaskStatus",
    "TaskStore",
    "UnknownDependencyError",
    "WorkflowError",
    "WorkflowTaskRecord",
    "claim_task",
    "complete_claim",
    "find_cycle",
    "ready_tasks",
    "release_claim",
    "run_workflow",
    "validate_dag",
]
