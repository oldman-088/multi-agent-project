"""Tests for bounded parallel scheduling: retries, replans, hard limits."""

from __future__ import annotations

import threading
import time

import pytest

from app.workflows.circuit import CircuitBreaker
from app.workflows.dag import TaskSpec
from app.workflows.errors import DAGCycleError, DAGValidationError, LimitExceededError
from app.workflows.limits import HardLimits, RetryPolicy
from app.workflows.scheduler import ReplanContext, RunReport, run_workflow
from app.workflows.status import RunStatus, TaskStatus


def spec(task_id: str, *deps: str, **kwargs: object) -> TaskSpec:
    return TaskSpec(task_id=task_id, depends_on=tuple(deps), **kwargs)  # type: ignore[arg-type]


class Recorder:
    """Thread-safe execution recorder with configurable behaviour."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls: list[str] = []
        self.live = 0
        self.peak = 0

    def execute(self, task: TaskSpec) -> str:
        with self.lock:
            self.calls.append(task.task_id)
            self.live += 1
            self.peak = max(self.peak, self.live)
        try:
            time.sleep(float(task.payload.get("sleep", 0.0)))
            if task.payload.get("fail"):
                raise RuntimeError(f"{task.task_id} exploded")
            return f"done:{task.task_id}"
        finally:
            with self.lock:
                self.live -= 1


class TestHappyPath:
    def test_runs_diamond_in_dependency_order(self) -> None:
        recorder = Recorder()
        report = run_workflow(
            [spec("a"), spec("b", "a"), spec("c", "a"), spec("d", "b", "c")],
            recorder.execute,
            limits=HardLimits(max_workers=4),
        )
        assert report.status is RunStatus.COMPLETED
        assert report.succeeded is True
        assert set(report.outcomes) == {"a", "b", "c", "d"}
        assert all(outcome.status is TaskStatus.SUCCEEDED for outcome in report.outcomes.values())
        order = recorder.calls
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")
        assert report.outcome("a").result == "done:a"
        assert report.steps_used == 4
        assert report.replans == 0

    def test_independent_tasks_run_concurrently(self) -> None:
        recorder = Recorder()
        report = run_workflow(
            [spec(f"t{i}", payload={"sleep": 0.05}) for i in range(6)],
            recorder.execute,
            limits=HardLimits(max_workers=6),
        )
        assert report.status is RunStatus.COMPLETED
        assert recorder.peak > 1  # bounded parallel, not serial

    def test_single_worker_is_serial(self) -> None:
        recorder = Recorder()
        report = run_workflow(
            [spec(f"t{i}", payload={"sleep": 0.01}) for i in range(3)],
            recorder.execute,
            limits=HardLimits(max_workers=1),
        )
        assert report.status is RunStatus.COMPLETED
        assert recorder.peak == 1


class TestHardLimitEnforcement:
    def test_workers_cap_limits_concurrency(self) -> None:
        recorder = Recorder()
        report = run_workflow(
            [spec(f"t{i}", payload={"sleep": 0.03}) for i in range(10)],
            recorder.execute,
            limits=HardLimits(max_workers=2),
            worker_ids=[f"worker-{i}" for i in range(10)],  # more names than the cap
        )
        assert report.status is RunStatus.COMPLETED
        assert recorder.peak <= 2  # hard cap held even with extra worker names

    def test_tasks_cap_rejects_oversized_plans(self) -> None:
        with pytest.raises(LimitExceededError) as excinfo:
            run_workflow(
                [spec(f"t{i}") for i in range(3)],
                Recorder().execute,
                limits=HardLimits(max_tasks=2),
            )
        assert excinfo.value.limit == "max_tasks"

    def test_steps_cap_stops_the_run(self) -> None:
        recorder = Recorder()
        report = run_workflow(
            [spec(f"t{i}") for i in range(5)],
            recorder.execute,
            limits=HardLimits(max_workers=1, max_steps=2),
        )
        assert report.status is RunStatus.STEP_LIMIT_REACHED
        assert report.steps_used == 2
        assert recorder.calls == ["t0", "t1"]
        cancelled = [o for o in report.outcomes.values() if o.status is TaskStatus.CANCELLED]
        assert len(cancelled) == 3
        assert all(o.error == "step limit reached" for o in cancelled)

    def test_time_cap_stops_dispatching(self) -> None:
        recorder = Recorder()
        report = run_workflow(
            [spec(f"t{i}", payload={"sleep": 0.05}) for i in range(20)],
            recorder.execute,
            limits=HardLimits(max_workers=1, max_seconds=0.12),
        )
        assert report.status is RunStatus.TIMED_OUT
        assert 1 <= report.steps_used <= 4  # dispatch stopped at the deadline
        cancelled = [o for o in report.outcomes.values() if o.status is TaskStatus.CANCELLED]
        assert len(cancelled) >= 16
        assert all(o.error == "time limit exceeded" for o in cancelled)
        assert report.elapsed_seconds >= 0.12  # in-flight attempts were drained

    def test_replan_consumes_steps(self) -> None:
        recorder = Recorder()

        def replan(context: ReplanContext) -> list[TaskSpec]:
            return [spec("fallback", payload={"ok": True})]

        report = run_workflow(
            [spec("a", payload={"fail": True}, max_attempts=1), spec("b", "a")],
            recorder.execute,
            limits=HardLimits(max_workers=1, max_steps=1),
            replan=replan,
        )
        # Only one step of budget: the failed attempt used it; the replan
        # (also a step) must not fit, so "b" is cancelled.
        assert report.steps_used == 1
        assert report.replans == 0
        assert report.status is RunStatus.FAILED


class TestRetries:
    def test_retry_then_success(self) -> None:
        attempts: list[str] = []
        sleeps: list[float] = []

        def execute(task: TaskSpec) -> str:
            attempts.append(task.task_id)
            if len(attempts) < 3:
                raise RuntimeError("flaky")
            return "ok"

        report = run_workflow(
            [spec("a")],
            execute,
            retry=RetryPolicy(max_attempts=3, backoff_seconds=0.01, backoff_multiplier=2.0),
            sleeper=sleeps.append,
        )
        assert report.status is RunStatus.COMPLETED
        outcome = report.outcome("a")
        assert outcome.status is TaskStatus.SUCCEEDED
        assert outcome.attempts == 3
        assert sleeps == [0.01, 0.02]  # exponential backoff between attempts

    def test_permanent_failure_cancels_dependents_but_not_siblings(self) -> None:
        recorder = Recorder()
        report = run_workflow(
            [spec("root", payload={"fail": True}), spec("child", "root"), spec("solo")],
            recorder.execute,
            retry=RetryPolicy(max_attempts=2),
        )
        assert report.status is RunStatus.FAILED
        assert report.outcome("root").status is TaskStatus.FAILED
        assert report.outcome("root").attempts == 2
        assert report.outcome("root").error is not None
        assert "exploded" in report.outcome("root").error
        assert report.outcome("child").status is TaskStatus.CANCELLED
        assert report.outcome("child").error == "dependency 'root' did not succeed"
        assert report.outcome("solo").status is TaskStatus.SUCCEEDED

    def test_cancellation_cascades_to_grandchildren(self) -> None:
        recorder = Recorder()
        report = run_workflow(
            [spec("a", payload={"fail": True}), spec("b", "a"), spec("c", "b")],
            recorder.execute,
            retry=RetryPolicy(max_attempts=1),
        )
        assert report.status is RunStatus.FAILED
        assert report.outcome("b").status is TaskStatus.CANCELLED
        assert report.outcome("c").status is TaskStatus.CANCELLED

    def test_per_task_max_attempts_overrides_policy(self) -> None:
        recorder = Recorder()
        report = run_workflow(
            [spec("a", payload={"fail": True}, max_attempts=1)],
            recorder.execute,
            retry=RetryPolicy(max_attempts=5),
        )
        assert report.outcome("a").attempts == 1


class TestReplanning:
    def test_replan_recovers_with_replacement(self) -> None:
        recorder = Recorder()
        replan_calls: list[ReplanContext] = []

        def replan(context: ReplanContext) -> list[TaskSpec]:
            replan_calls.append(context)
            return [spec("a-fallback", payload={})]

        report = run_workflow(
            [spec("a", payload={"fail": True}, max_attempts=1), spec("b", "a")],
            recorder.execute,
            limits=HardLimits(max_workers=1),
            replan=replan,
        )
        assert len(replan_calls) == 1
        assert replan_calls[0].failed_task.task_id == "a"
        assert replan_calls[0].attempts == 1
        assert "exploded" in (replan_calls[0].error or "")
        assert report.replans == 1
        # The failed task is recorded, its replacement succeeded, and the
        # dependents were rewired onto the replacement.
        assert report.outcome("a").status is TaskStatus.FAILED
        assert report.outcome("a-fallback").status is TaskStatus.SUCCEEDED
        assert report.outcome("b").status is TaskStatus.SUCCEEDED
        assert report.status is RunStatus.COMPLETED  # recovered by the replan
        assert recorder.calls.index("a-fallback") < recorder.calls.index("b")

    def test_replan_with_no_replacements_cancels_dependents(self) -> None:
        recorder = Recorder()

        def replan(context: ReplanContext) -> list[TaskSpec]:
            return []

        report = run_workflow(
            [spec("a", payload={"fail": True}, max_attempts=1), spec("b", "a")],
            recorder.execute,
            replan=replan,
        )
        assert report.replans == 1
        assert report.outcome("a").status is TaskStatus.FAILED
        assert report.outcome("b").status is TaskStatus.CANCELLED
        assert report.status is RunStatus.FAILED

    def test_replan_cannot_exceed_the_tasks_cap(self) -> None:
        recorder = Recorder()

        def replan(context: ReplanContext) -> list[TaskSpec]:
            return [spec("x"), spec("y")]

        with pytest.raises(LimitExceededError) as excinfo:
            run_workflow(
                [spec("a", payload={"fail": True}, max_attempts=1), spec("b")],
                recorder.execute,
                limits=HardLimits(max_tasks=2),
                replan=replan,
            )
        assert excinfo.value.limit == "max_tasks"

    def test_replan_may_not_depend_on_the_failed_task(self) -> None:
        recorder = Recorder()

        def replan(context: ReplanContext) -> list[TaskSpec]:
            return [spec("x", "a")]

        with pytest.raises(DAGValidationError):
            run_workflow(
                [spec("a", payload={"fail": True}, max_attempts=1)],
                recorder.execute,
                replan=replan,
            )

    def test_replan_may_not_duplicate_task_ids(self) -> None:
        recorder = Recorder()

        def replan(context: ReplanContext) -> list[TaskSpec]:
            return [spec("b")]

        with pytest.raises(DAGValidationError):
            run_workflow(
                [spec("a", payload={"fail": True}, max_attempts=1), spec("b")],
                recorder.execute,
                replan=replan,
            )

    def test_repeated_failures_can_replan_twice(self) -> None:
        recorder = Recorder()

        def replan(context: ReplanContext) -> list[TaskSpec]:
            if context.failed_task.task_id == "a":
                return [spec("a2", payload={"fail": True}, max_attempts=1)]
            return [spec("a3")]

        report = run_workflow(
            [spec("a", payload={"fail": True}, max_attempts=1), spec("b", "a")],
            recorder.execute,
            replan=replan,
        )
        assert report.replans == 2
        assert report.outcome("a2").status is TaskStatus.FAILED
        assert report.outcome("a3").status is TaskStatus.SUCCEEDED
        assert report.outcome("b").status is TaskStatus.SUCCEEDED
        assert report.status is RunStatus.COMPLETED


class TestCircuitIntegration:
    def test_open_circuit_fails_fast_without_execution(self) -> None:
        calls: list[str] = []

        def execute(task: TaskSpec) -> str:
            calls.append(task.task_id)
            raise RuntimeError("always")

        breaker = CircuitBreaker(failure_threshold=2, reset_timeout=60.0)
        report = run_workflow(
            [spec(f"t{i}", max_attempts=1) for i in range(4)],
            execute,
            limits=HardLimits(max_workers=1),
            circuit_breaker=breaker,
        )
        assert report.status is RunStatus.FAILED
        # Threshold 2: only the first two tasks reach the executor; the rest
        # fail fast through the open circuit.
        assert calls == ["t0", "t1"]
        assert all(outcome.status is TaskStatus.FAILED for outcome in report.outcomes.values())

    def test_per_kind_breakers(self) -> None:
        calls: list[str] = []

        def execute(task: TaskSpec) -> str:
            calls.append(task.kind)
            if task.kind == "fragile":
                raise RuntimeError("kind failure")
            return "ok"

        breakers = {"fragile": CircuitBreaker(failure_threshold=1, reset_timeout=60.0)}
        report = run_workflow(
            [
                spec("f1", payload={}, max_attempts=1, kind="fragile"),
                spec("f2", payload={}, max_attempts=1, kind="fragile"),
                spec("s1", payload={}, kind="stable"),
            ],
            execute,
            limits=HardLimits(max_workers=1),
            circuit_breakers=breakers,
        )
        assert calls == ["fragile", "stable"]  # f2 blocked by the open circuit
        assert report.outcome("s1").status is TaskStatus.SUCCEEDED


class TestPlanValidation:
    def test_cycle_in_plan_is_rejected_before_running(self) -> None:
        recorder = Recorder()
        with pytest.raises(DAGCycleError):
            run_workflow([spec("a", "b"), spec("b", "a")], recorder.execute)
        assert recorder.calls == []

    def test_empty_worker_ids_rejected(self) -> None:
        with pytest.raises(ValueError):
            run_workflow([spec("a")], Recorder().execute, worker_ids=[])


class TestTaskSpecKinds:
    def test_payload_reaches_the_executor(self) -> None:
        seen: list[dict[str, object]] = []

        def execute(task: TaskSpec) -> str:
            seen.append(dict(task.payload))
            return "ok"

        run_workflow([spec("a", payload={"n": 7})], execute)
        assert seen == [{"n": 7}]


def test_report_outcome_lookup() -> None:
    report: RunReport = run_workflow([spec("a")], lambda task: "ok")
    assert report.outcome("a").result == "ok"


def test_clock_is_used_for_elapsed() -> None:
    ticks = [0.0]

    def clock() -> float:
        return ticks[0]

    def execute(task: TaskSpec) -> str:
        ticks[0] += 5.0
        return "ok"

    report = run_workflow([spec("a")], execute, clock=clock)
    assert report.elapsed_seconds == 5.0
