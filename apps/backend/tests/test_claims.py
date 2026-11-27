"""Tests for atomic task claims (SQLite; the same statements run on PostgreSQL)."""

from __future__ import annotations

import threading
from collections.abc import Callable

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.workflows.claims import (
    Claim,
    cancel_task,
    claim_task,
    complete_claim,
    release_claim,
)
from app.workflows.errors import ClaimConflictError
from app.workflows.models import WorkflowTaskRecord
from app.workflows.status import TaskStatus


def add_task(
    session: Session,
    task_id: str,
    *,
    max_attempts: int = 3,
    workflow_id: str = "wf",
) -> None:
    session.add(
        WorkflowTaskRecord(
            id=task_id,
            workflow_id=workflow_id,
            task_key=task_id,
            status=TaskStatus.PENDING.value,
            attempts=0,
            max_attempts=max_attempts,
        )
    )
    session.commit()


def get_row(session: Session, task_id: str) -> WorkflowTaskRecord:
    row = session.get(WorkflowTaskRecord, task_id)
    assert row is not None
    return row


class TestClaim:
    def test_claim_succeeds_and_stamps_token(self, session_factory: Callable[[], Session]) -> None:
        session = session_factory()
        add_task(session, "t1")
        claim = claim_task(session, "t1", "worker-0")
        session.commit()
        assert claim is not None
        assert claim.task_id == "t1"
        assert claim.worker_id == "worker-0"
        assert claim.attempts == 1
        row = get_row(session, "t1")
        assert row.status == TaskStatus.CLAIMED.value
        assert row.claim_token == claim.claim_token
        assert row.claimed_by == "worker-0"
        session.close()

    def test_second_claim_returns_none(self, session_factory: Callable[[], Session]) -> None:
        session = session_factory()
        add_task(session, "t1")
        first = claim_task(session, "t1", "worker-0")
        second = claim_task(session, "t1", "worker-1")
        session.commit()
        assert first is not None
        assert second is None
        session.close()

    def test_claim_unknown_task_returns_none(self, session_factory: Callable[[], Session]) -> None:
        session = session_factory()
        assert claim_task(session, "ghost", "worker-0") is None
        session.close()

    def test_rejects_empty_worker(self, session_factory: Callable[[], Session]) -> None:
        session = session_factory()
        add_task(session, "t1")
        with pytest.raises(ValueError):
            claim_task(session, "t1", "")
        session.close()

    def test_attempt_cap_blocks_further_claims(
        self, session_factory: Callable[[], Session]
    ) -> None:
        session = session_factory()
        add_task(session, "t1", max_attempts=2)
        claim = claim_task(session, "t1", "worker-0")
        assert claim is not None
        assert claim.attempts == 1
        assert release_claim(session, "t1", claim.claim_token, requeue=True) is TaskStatus.PENDING
        session.commit()
        # A pending row that has already burned its attempts must not be
        # claimable: the atomic UPDATE requires attempts < max_attempts.
        session.execute(
            sa.update(WorkflowTaskRecord).where(WorkflowTaskRecord.id == "t1").values(attempts=2)
        )
        session.commit()
        assert claim_task(session, "t1", "worker-0") is None
        session.close()


class TestComplete:
    def test_complete_with_success(self, session_factory: Callable[[], Session]) -> None:
        session = session_factory()
        add_task(session, "t1")
        claim = claim_task(session, "t1", "worker-0")
        assert claim is not None
        complete_claim(
            session, "t1", claim.claim_token, status=TaskStatus.SUCCEEDED, result={"ok": 1}
        )
        session.commit()
        row = get_row(session, "t1")
        assert row.status == TaskStatus.SUCCEEDED.value
        assert row.result_json == {"ok": 1}
        assert row.claim_token is None
        session.close()

    def test_complete_with_failure_records_error(
        self, session_factory: Callable[[], Session]
    ) -> None:
        session = session_factory()
        add_task(session, "t1")
        claim = claim_task(session, "t1", "worker-0")
        assert claim is not None
        complete_claim(session, "t1", claim.claim_token, status=TaskStatus.FAILED, error="boom")
        session.commit()
        row = get_row(session, "t1")
        assert row.status == TaskStatus.FAILED.value
        assert row.error == "boom"
        session.close()

    def test_wrong_token_is_rejected(self, session_factory: Callable[[], Session]) -> None:
        session = session_factory()
        add_task(session, "t1")
        claim = claim_task(session, "t1", "worker-0")
        assert claim is not None
        with pytest.raises(ClaimConflictError):
            complete_claim(session, "t1", "wrong-token", status=TaskStatus.SUCCEEDED, result=None)
        session.rollback()
        session.close()

    def test_double_completion_is_rejected(self, session_factory: Callable[[], Session]) -> None:
        session = session_factory()
        add_task(session, "t1")
        claim = claim_task(session, "t1", "worker-0")
        assert claim is not None
        complete_claim(session, "t1", claim.claim_token, status=TaskStatus.SUCCEEDED)
        session.commit()
        with pytest.raises(ClaimConflictError):
            complete_claim(session, "t1", claim.claim_token, status=TaskStatus.SUCCEEDED)
        session.rollback()
        session.close()

    def test_rejects_non_terminal_status(self, session_factory: Callable[[], Session]) -> None:
        session = session_factory()
        add_task(session, "t1")
        claim = claim_task(session, "t1", "worker-0")
        assert claim is not None
        with pytest.raises(ValueError):
            complete_claim(session, "t1", claim.claim_token, status=TaskStatus.RUNNING)
        session.close()


class TestRelease:
    def test_release_requeues_while_attempts_remain(
        self, session_factory: Callable[[], Session]
    ) -> None:
        session = session_factory()
        add_task(session, "t1", max_attempts=3)
        claim = claim_task(session, "t1", "worker-0")
        assert claim is not None
        status = release_claim(session, "t1", claim.claim_token, error="retry me", requeue=True)
        session.commit()
        assert status is TaskStatus.PENDING
        row = get_row(session, "t1")
        assert row.status == TaskStatus.PENDING.value
        assert row.attempts == 1
        assert row.error == "retry me"
        # The task is claimable again for attempt 2.
        again = claim_task(session, "t1", "worker-1")
        session.commit()
        assert again is not None
        assert again.attempts == 2
        session.close()

    def test_release_fails_task_when_attempts_exhausted(
        self, session_factory: Callable[[], Session]
    ) -> None:
        session = session_factory()
        add_task(session, "t1", max_attempts=1)
        claim = claim_task(session, "t1", "worker-0")
        assert claim is not None
        status = release_claim(session, "t1", claim.claim_token, error="dead", requeue=True)
        session.commit()
        assert status is TaskStatus.FAILED
        assert claim_task(session, "t1", "worker-0") is None  # out of attempts
        session.close()

    def test_release_without_requeue_fails_task(
        self, session_factory: Callable[[], Session]
    ) -> None:
        session = session_factory()
        add_task(session, "t1", max_attempts=5)
        claim = claim_task(session, "t1", "worker-0")
        assert claim is not None
        status = release_claim(session, "t1", claim.claim_token, error="dead", requeue=False)
        session.commit()
        assert status is TaskStatus.FAILED
        session.close()

    def test_release_with_wrong_token_is_rejected(
        self, session_factory: Callable[[], Session]
    ) -> None:
        session = session_factory()
        add_task(session, "t1")
        claim = claim_task(session, "t1", "worker-0")
        assert claim is not None
        with pytest.raises(ClaimConflictError):
            release_claim(session, "t1", "wrong", requeue=True)
        session.close()


class TestCancel:
    def test_cancel_pending_task(self, session_factory: Callable[[], Session]) -> None:
        session = session_factory()
        add_task(session, "t1")
        assert cancel_task(session, "t1", reason="time limit exceeded") is True
        session.commit()
        row = get_row(session, "t1")
        assert row.status == TaskStatus.CANCELLED.value
        assert row.error == "time limit exceeded"
        session.close()

    def test_cancel_refuses_held_task(self, session_factory: Callable[[], Session]) -> None:
        session = session_factory()
        add_task(session, "t1")
        claim = claim_task(session, "t1", "worker-0")
        assert claim is not None
        assert cancel_task(session, "t1", reason="nope") is False
        session.close()


class TestConcurrency:
    def test_concurrent_claims_have_exactly_one_winner(
        self, session_factory: Callable[[], Session]
    ) -> None:
        """The atomic UPDATE guarantees one winner across threads/processes."""
        session = session_factory()
        add_task(session, "t1", max_attempts=5)
        session.close()

        winners: list[Claim] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(8)

        def race() -> None:
            thread_session = session_factory()
            try:
                barrier.wait(timeout=30)
                claim = claim_task(thread_session, "t1", f"worker-{threading.get_ident()}")
                thread_session.commit()
                if claim is not None:
                    winners.append(claim)
            except BaseException as exc:  # noqa: BLE001 - recorded and asserted below
                errors.append(exc)
            finally:
                thread_session.close()

        threads = [threading.Thread(target=race) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert not errors, f"claim raised: {errors}"
        assert len(winners) == 1
        check = session_factory()
        row = get_row(check, "t1")
        assert row.status == TaskStatus.CLAIMED.value
        assert row.claimed_by == winners[0].worker_id
        assert row.attempts == 1
        check.close()
