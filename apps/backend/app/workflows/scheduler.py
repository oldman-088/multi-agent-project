"""Bounded parallel workflow scheduling: dispatch, retries, replans, hard limits.

Implements the workforce-engine contract from docs/SPEC.md (Phase 3): "runs
independent tasks concurrently within limits, retries failed tasks, replans on
repeated failure, and aggregates results.  Hard caps on workers, concurrency,
time and steps."

Guarantees enforced at run time (tested in ``apps/backend/tests``):

- at most ``limits.max_workers`` attempts run concurrently, on named workers;
- no more than ``limits.max_tasks`` tasks ever exist (replans included);
- no new attempt is dispatched after ``limits.max_seconds`` (in-flight
  attempts are drained — Python threads cannot be killed);
- every dispatched attempt and every replan consumes one step; the run stops
  at ``limits.max_steps``;
- a task is retried per the :class:`~app.workflows.limits.RetryPolicy`, then
  fails permanently; on permanent failure the plan is replanned (replacement
  tasks, dependents rewired) or the dependents are cancelled.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from typing import Any

from .circuit import CircuitBreaker
from .claims import Claim
from .dag import TaskSpec, dependency_map, validate_dag
from .errors import DAGValidationError, LimitExceededError
from .limits import HardLimits, RetryPolicy
from .status import RunStatus, TaskStatus
from .store import TaskStore

Executor = Callable[[TaskSpec], Any]
ReplanFn = Callable[["ReplanContext"], Sequence[TaskSpec]]


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    """Terminal result of one task."""

    task_id: str
    status: TaskStatus
    attempts: int
    result: Any = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ReplanContext:
    """Handed to the replan callback after a task failed permanently."""

    failed_task: TaskSpec
    attempts: int
    error: str | None
    outcomes: Mapping[str, TaskOutcome]


@dataclass(frozen=True, slots=True)
class RunReport:
    """Aggregated result of one workflow run."""

    status: RunStatus
    outcomes: Mapping[str, TaskOutcome]
    steps_used: int
    replans: int
    elapsed_seconds: float

    @property
    def succeeded(self) -> bool:
        return self.status is RunStatus.COMPLETED

    def outcome(self, task_id: str) -> TaskOutcome:
        return self.outcomes[task_id]


@dataclass(frozen=True, slots=True)
class _InFlight:
    spec: TaskSpec
    worker_id: str
    attempt: int
    claim: Claim | None


def effective_max_attempts(spec: TaskSpec, retry: RetryPolicy) -> int:
    """Per-task attempt cap, falling back to the run's retry policy."""
    return spec.max_attempts if spec.max_attempts is not None else retry.max_attempts


def run_workflow(
    tasks: Sequence[TaskSpec],
    execute: Executor,
    *,
    limits: HardLimits | None = None,
    retry: RetryPolicy | None = None,
    replan: ReplanFn | None = None,
    store: TaskStore | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    circuit_breakers: Mapping[str, CircuitBreaker] | None = None,
    worker_ids: Sequence[str] | None = None,
    workflow_id: str = "workflow",
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> RunReport:
    """Run a task DAG to completion under hard limits.

    Args:
        tasks: The plan; dependency cycles and duplicate ids are rejected.
        execute: Runs one task; exceptions count as failed attempts.
        limits: Hard caps (workers, tasks, seconds, steps).
        retry: Retry policy for failed attempts.
        replan: Called after a task fails permanently; returns replacement
            tasks.  Dependents of the failed task are rewired onto the
            replacements.  Every invocation consumes one step and may not push
            the plan past ``limits.max_tasks``.
        store: Optional durable store; when given, every dispatch goes through
            an atomic claim and outcomes are persisted.
        circuit_breaker: Breaker wrapping every execution (per-kind overrides
            via ``circuit_breakers``).
        worker_ids: Worker slot names; truncated to ``limits.max_workers``.
        workflow_id: Identifies the run inside ``store``.
        clock: Monotonic time source (injectable for tests).
        sleeper: Backoff sleep (injectable for tests).

    Returns:
        A :class:`RunReport` aggregating every task outcome.

    Raises:
        LimitExceededError: The plan (or a replan) exceeds ``limits.max_tasks``.
        DAGValidationError: The plan, or a replan result, is not a valid DAG.
        ValueError: Empty ``worker_ids`` or an invalid argument.
    """
    limits = limits or HardLimits()
    retry = retry or RetryPolicy()
    specs_list = list(tasks)
    if len(specs_list) > limits.max_tasks:
        raise LimitExceededError("max_tasks", len(specs_list), limits.max_tasks)

    graph: dict[str, tuple[str, ...]] = dependency_map(specs_list)
    validate_dag(graph)
    specs: dict[str, TaskSpec] = {spec.task_id: spec for spec in specs_list}

    workers = (
        list(worker_ids)
        if worker_ids is not None
        else [f"worker-{index}" for index in range(limits.max_workers)]
    )
    if not workers:
        raise ValueError("worker_ids must be a non-empty sequence")
    if len(workers) > limits.max_workers:
        workers = workers[: limits.max_workers]  # hard cap on workers
    max_concurrent = len(workers)

    outcomes: dict[str, TaskOutcome] = {}
    attempts: dict[str, int] = {}
    recovered_from: dict[str, tuple[str, ...]] = {}
    in_flight: dict[Future[tuple[bool, object]], _InFlight] = {}
    free_workers = list(workers)
    steps_used = 0
    replans = 0
    timed_out = False
    steps_exhausted = False

    def max_attempts_of(spec: TaskSpec) -> int:
        return effective_max_attempts(spec, retry)

    def breaker_for(spec: TaskSpec) -> CircuitBreaker | None:
        if circuit_breakers is not None and spec.kind in circuit_breakers:
            return circuit_breakers[spec.kind]
        return circuit_breaker

    def attempt(spec: TaskSpec, attempt_no: int) -> tuple[bool, object]:
        breaker = breaker_for(spec)

        def run() -> Any:
            return execute(spec)

        try:
            result = breaker.call(run) if breaker is not None else run()
        except Exception as exc:  # noqa: BLE001 - failure is data, not control flow
            delay = retry.delay_before_retry(attempt_no)
            if attempt_no < max_attempts_of(spec) and delay > 0:
                sleeper(delay)  # backoff before the retry becomes dispatchable
            return (False, f"{type(exc).__name__}: {exc}")
        return (True, result)

    def prune_blocked() -> bool:
        """Cancel every task whose dependencies cannot succeed any more.

        Runs to a fixed point (one cancellation can block its own dependents),
        so a whole dead subtree is cancelled in one call.  Returns whether
        anything changed.
        """
        changed = False
        for task_id in sorted(specs):
            if task_id in outcomes or any(
                record.spec.task_id == task_id for record in in_flight.values()
            ):
                continue
            for dep in graph[task_id]:
                outcome = outcomes.get(dep)
                if outcome is not None and outcome.status is not TaskStatus.SUCCEEDED:
                    outcomes[task_id] = TaskOutcome(
                        task_id=task_id,
                        status=TaskStatus.CANCELLED,
                        attempts=attempts.get(task_id, 0),
                        error=f"dependency {dep!r} did not succeed",
                    )
                    if store is not None:
                        store.cancel(task_id, f"dependency {dep!r} did not succeed")
                    changed = True
                    break
        return changed

    def ready_now() -> list[str]:
        active = {record.spec.task_id for record in in_flight.values()}
        return [
            task_id
            for task_id in sorted(specs)
            if task_id not in outcomes
            and task_id not in active
            and all(
                dep in outcomes and outcomes[dep].status is TaskStatus.SUCCEEDED
                for dep in graph[task_id]
            )
        ]

    def apply_replacements(failed: TaskSpec, replacements: Sequence[TaskSpec]) -> None:
        new_total = len(specs) + len(replacements)
        if new_total > limits.max_tasks:
            raise LimitExceededError("max_tasks", new_total, limits.max_tasks)
        seen: set[str] = set()
        for replacement in replacements:
            if not isinstance(replacement, TaskSpec):
                raise DAGValidationError(
                    f"replan must return TaskSpec instances, got {type(replacement).__name__}"
                )
            if replacement.task_id in specs or replacement.task_id in seen:
                raise DAGValidationError(
                    f"replan produced duplicate task id {replacement.task_id!r}"
                )
            if failed.task_id in replacement.depends_on:
                raise DAGValidationError(
                    f"replacement task {replacement.task_id!r} may not depend on the failed task"
                )
            seen.add(replacement.task_id)
        for task_id, spec in list(specs.items()):
            if task_id in outcomes or failed.task_id not in spec.depends_on:
                continue
            rewired = tuple(d for d in spec.depends_on if d != failed.task_id) + tuple(
                replacement.task_id for replacement in replacements
            )
            specs[task_id] = replace(spec, depends_on=rewired)
            graph[task_id] = rewired
        for replacement in replacements:
            specs[replacement.task_id] = replacement
            graph[replacement.task_id] = tuple(replacement.depends_on)
            attempts.setdefault(replacement.task_id, 0)
        validate_dag(graph)  # a bad replan raises before it can corrupt the run
        recovered_from[failed.task_id] = tuple(r.task_id for r in replacements)
        if store is not None:
            store.register(
                [
                    replace(replacement, max_attempts=max_attempts_of(replacement))
                    for replacement in replacements
                ]
            )

    def handle_permanent_failure(spec: TaskSpec, error: str) -> None:
        nonlocal replans, steps_used
        if replan is not None and steps_used < limits.max_steps:
            steps_used += 1
            replans += 1
            context = ReplanContext(
                failed_task=spec,
                attempts=attempts.get(spec.task_id, 0),
                error=error,
                outcomes=dict(outcomes),
            )
            replacements = tuple(replan(context))
            if replacements:
                apply_replacements(spec, replacements)
                return
        # No replan (or none possible): dependents are cancelled by prune_blocked().

    def process(future: Future[tuple[bool, object]]) -> None:
        record = in_flight.pop(future)
        free_workers.append(record.worker_id)
        ok, payload = future.result()
        task_id = record.spec.task_id
        if ok:
            outcomes[task_id] = TaskOutcome(
                task_id=task_id,
                status=TaskStatus.SUCCEEDED,
                attempts=record.attempt,
                result=payload,
            )
            if store is not None and record.claim is not None:
                store.succeed(record.claim, payload)
            return
        error = str(payload)
        if record.attempt < max_attempts_of(record.spec):
            if store is not None and record.claim is not None:
                store.fail(record.claim, error, requeue=True)
            return  # the task becomes ready again for a retry
        outcomes[task_id] = TaskOutcome(
            task_id=task_id,
            status=TaskStatus.FAILED,
            attempts=record.attempt,
            error=error,
        )
        if store is not None and record.claim is not None:
            store.fail(record.claim, error, requeue=False)
        handle_permanent_failure(record.spec, error)

    start = clock()
    deadline = start + limits.max_seconds
    pool = ThreadPoolExecutor(max_workers=max_concurrent, thread_name_prefix="workflow")
    try:
        if store is not None:
            store.register(
                [replace(spec, max_attempts=max_attempts_of(spec)) for spec in specs_list]
            )
        while True:
            while prune_blocked():
                pass
            queue = ready_now()
            while (
                queue
                and len(in_flight) < max_concurrent
                and free_workers
                and steps_used < limits.max_steps
                and clock() < deadline
            ):
                task_id = queue.pop(0)
                spec = specs[task_id]
                worker_id = free_workers.pop(0)
                claim = store.claim(task_id, worker_id) if store is not None else None
                if store is not None and claim is None:
                    outcomes[task_id] = TaskOutcome(
                        task_id=task_id,
                        status=TaskStatus.CANCELLED,
                        attempts=attempts.get(task_id, 0),
                        error="task could not be claimed (taken elsewhere or out of attempts)",
                    )
                    free_workers.append(worker_id)
                    continue
                steps_used += 1
                attempt_no = attempts.get(task_id, 0) + 1
                attempts[task_id] = attempt_no
                future = pool.submit(attempt, spec, attempt_no)
                in_flight[future] = _InFlight(spec, worker_id, attempt_no, claim)

            if in_flight:
                timeout = None if timed_out else max(0.0, deadline - clock())
                done, _ = wait(set(in_flight), return_when=FIRST_COMPLETED, timeout=timeout)
                if not done:
                    timed_out = True  # deadline reached with attempts still running
                    continue  # drain in-flight attempts without a timeout
                for future in done:
                    process(future)
                continue

            if not any(task_id not in outcomes for task_id in specs):
                break  # everything finished
            if clock() >= deadline:
                timed_out = True
                break
            if steps_used >= limits.max_steps:
                steps_exhausted = True
                break
            # Safety net (unreachable for a valid DAG): no work running or
            # ready, yet tasks remain — cancel them so every task has an outcome.
            break
    finally:
        pool.shutdown(wait=True)

    if timed_out:
        reason = "time limit exceeded"
    elif steps_exhausted:
        reason = "step limit reached"
    else:
        reason = "run stopped"
    for task_id in sorted(specs):
        if task_id not in outcomes and not any(
            record.spec.task_id == task_id for record in in_flight.values()
        ):
            outcomes[task_id] = TaskOutcome(
                task_id=task_id,
                status=TaskStatus.CANCELLED,
                attempts=attempts.get(task_id, 0),
                error=reason,
            )
            if store is not None:
                store.cancel(task_id, reason)

    if timed_out:
        status = RunStatus.TIMED_OUT
    elif steps_exhausted:
        status = RunStatus.STEP_LIMIT_REACHED
    else:

        def recovered(task_id: str) -> bool:
            """A failure is recovered when its replacements all succeeded,
            possibly through a chain of replans (a -> a2 -> a3)."""
            replacement_ids = recovered_from.get(task_id, ())
            if not replacement_ids:
                return False
            for replacement_id in replacement_ids:
                outcome = outcomes.get(replacement_id)
                if outcome is None:
                    return False
                if outcome.status is TaskStatus.FAILED and recovered(replacement_id):
                    continue
                if outcome.status is not TaskStatus.SUCCEEDED:
                    return False
            return True

        status = RunStatus.COMPLETED
        for task_id, outcome in outcomes.items():
            if outcome.status is TaskStatus.SUCCEEDED or (
                outcome.status is TaskStatus.FAILED and recovered(task_id)
            ):
                continue
            status = RunStatus.FAILED
            break

    return RunReport(
        status=status,
        outcomes=dict(outcomes),
        steps_used=steps_used,
        replans=replans,
        elapsed_seconds=clock() - start,
    )
