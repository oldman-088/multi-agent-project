"""Tests for the durable task store and store-backed scheduler runs."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.workflows.claims import Claim
from app.workflows.dag import TaskSpec
from app.workflows.limits import HardLimits, RetryPolicy
from app.workflows.models import WorkflowTaskRecord
from app.workflows.scheduler import run_workflow
from app.workflows.status import RunStatus, TaskStatus
from app.workflows.store import SqlAlchemyTaskStore


def spec(task_id: str, *deps: str, **kwargs: object) -> TaskSpec:
    return TaskSpec(task_id=task_id, depends_on=tuple(deps), **kwargs)  # type: ignore[arg-type]


def rows_by_key(session: Session, workflow_id: str) -> dict[str, WorkflowTaskRecord]:
    rows = session.execute(
        select(WorkflowTaskRecord).where(WorkflowTaskRecord.workflow_id == workflow_id)
    ).scalars()
    return {row.task_key: row for row in rows}


class TestSqlAlchemyTaskStore:
    def test_register_claim_succeed(self, session_factory: Callable[[], Session]) -> None:
        store = SqlAlchemyTaskStore(session_factory, workflow_id="wf1")
        store.register([spec("t1", payload={"n": 1}, max_attempts=3)])
        claim = store.claim("t1", "worker-0")
        assert claim is not None
        assert claim.attempts == 1
        store.succeed(claim, {"ok": True})
        session = session_factory()
        row = rows_by_key(session, "wf1")["t1"]
        assert row.status == TaskStatus.SUCCEEDED.value
        assert row.result_json == {"ok": True}
        assert row.payload_json == {"n": 1}
        assert row.claimed_by == "worker-0"
        session.close()

    def test_claim_is_exclusive(self, session_factory: Callable[[], Session]) -> None:
        store = SqlAlchemyTaskStore(session_factory, workflow_id="wf1")
        store.register([spec("t1", max_attempts=3)])
        first = store.claim("t1", "worker-0")
        second = store.claim("t1", "worker-1")
        assert first is not None
        assert second is None

    def test_fail_requeue_then_fail_permanent(self, session_factory: Callable[[], Session]) -> None:
        store = SqlAlchemyTaskStore(session_factory, workflow_id="wf1")
        store.register([spec("t1", max_attempts=2)])
        claim = store.claim("t1", "worker-0")
        assert claim is not None
        store.fail(claim, "first failure", requeue=True)
        session = session_factory()
        row = rows_by_key(session, "wf1")["t1"]
        assert row.status == TaskStatus.PENDING.value
        assert row.attempts == 1
        session.close()
        again = store.claim("t1", "worker-0")
        assert again is not None
        store.fail(again, "second failure", requeue=True)  # out of attempts -> failed
        session = session_factory()
        row = rows_by_key(session, "wf1")["t1"]
        assert row.status == TaskStatus.FAILED.value
        assert row.error == "second failure"
        session.close()

    def test_cancel(self, session_factory: Callable[[], Session]) -> None:
        store = SqlAlchemyTaskStore(session_factory, workflow_id="wf1")
        store.register([spec("t1")])
        store.cancel("t1", "time limit exceeded")
        session = session_factory()
        row = rows_by_key(session, "wf1")["t1"]
        assert row.status == TaskStatus.CANCELLED.value
        assert row.error == "time limit exceeded"
        session.close()

    def test_unknown_task_claim_returns_none(self, session_factory: Callable[[], Session]) -> None:
        store = SqlAlchemyTaskStore(session_factory, workflow_id="wf1")
        assert store.claim("ghost", "worker-0") is None


class TestStoreBackedRun:
    def test_run_persists_every_outcome(self, session_factory: Callable[[], Session]) -> None:
        store = SqlAlchemyTaskStore(session_factory, workflow_id="run-1")

        def execute(task: TaskSpec) -> str:
            if task.task_id == "bad":
                raise RuntimeError("bad task")
            return f"ok:{task.task_id}"

        report = run_workflow(
            [
                spec("good"),
                spec("bad", max_attempts=1),
                spec("child", "bad"),
            ],
            execute,
            limits=HardLimits(max_workers=2),
            retry=RetryPolicy(max_attempts=1),
            store=store,
            workflow_id="run-1",
        )
        assert report.status is RunStatus.FAILED
        session = session_factory()
        rows = rows_by_key(session, "run-1")
        assert rows["good"].status == TaskStatus.SUCCEEDED.value
        assert rows["good"].result_json == "ok:good"
        assert rows["bad"].status == TaskStatus.FAILED.value
        assert rows["bad"].error is not None and "bad task" in rows["bad"].error
        assert rows["child"].status == TaskStatus.CANCELLED.value
        session.close()

    def test_workers_capped_in_claims(self, session_factory: Callable[[], Session]) -> None:
        store = SqlAlchemyTaskStore(session_factory, workflow_id="run-2")
        report = run_workflow(
            [spec(f"t{i}") for i in range(4)],
            lambda task: "ok",
            limits=HardLimits(max_workers=2),
            store=store,
            worker_ids=[f"worker-{i}" for i in range(8)],
            workflow_id="run-2",
        )
        assert report.status is RunStatus.COMPLETED
        session = session_factory()
        rows = rows_by_key(session, "run-2")
        claimers = {row.claimed_by for row in rows.values()}
        assert claimers <= {"worker-0", "worker-1"}  # hard cap on workers
        assert all(row.status == TaskStatus.SUCCEEDED.value for row in rows.values())
        session.close()

    def test_replan_adds_rows(self, session_factory: Callable[[], Session]) -> None:
        store = SqlAlchemyTaskStore(session_factory, workflow_id="run-3")

        def execute(task: TaskSpec) -> str:
            if task.task_id == "a":
                raise RuntimeError("fall")
            return "ok"

        def replan(context: object) -> list[TaskSpec]:
            return [spec("a-fallback")]

        report = run_workflow(
            [spec("a", max_attempts=1), spec("b", "a")],
            execute,
            limits=HardLimits(max_workers=1),
            retry=RetryPolicy(max_attempts=1),
            replan=replan,
            store=store,
            workflow_id="run-3",
        )
        assert report.status is RunStatus.COMPLETED
        session = session_factory()
        rows = rows_by_key(session, "run-3")
        assert set(rows) == {"a", "b", "a-fallback"}
        assert rows["a-fallback"].status == TaskStatus.SUCCEEDED.value
        session.close()


def test_claim_dataclass_is_immutable() -> None:
    claim = Claim(task_id="t", claim_token="tok", worker_id="w", attempts=1)
    try:
        claim.attempts = 2  # type: ignore[misc]
    except AttributeError:
        pass
    else:  # pragma: no cover - dataclass(frozen=True) must prevent this
        raise AssertionError("Claim must be frozen")
