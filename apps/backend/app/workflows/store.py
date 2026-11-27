"""Durable task store: the scheduler's claims go through the database.

:class:`SqlAlchemyTaskStore` implements the small :class:`TaskStore` protocol
used by :mod:`app.workflows.scheduler` on top of the ``workflow_tasks`` table
and the atomic functions in :mod:`app.workflows.claims`.  One store instance
belongs to one workflow run (``workflow_id``).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import claims as claims_api
from .claims import Claim
from .dag import TaskSpec
from .errors import ClaimConflictError
from .models import WorkflowTaskRecord
from .status import TaskStatus


class TaskStore(Protocol):
    """What the scheduler needs from a durable (or fake) task store."""

    def register(self, specs: Sequence[TaskSpec]) -> None:
        """Persist task rows; called with tasks that are not stored yet."""

    def claim(self, task_id: str, worker_id: str) -> Claim | None:
        """Atomically claim a task; ``None`` when not claimable."""

    def succeed(self, claim: Claim, result: Any) -> None:
        """Complete the claim with a success result."""

    def fail(self, claim: Claim, error: str, *, requeue: bool) -> None:
        """Release the claim after a failed attempt (requeue or fail)."""

    def cancel(self, task_id: str, reason: str) -> None:
        """Cancel an unclaimed task."""


class SqlAlchemyTaskStore:
    """TaskStore backed by the ``workflow_tasks`` table.

    Each operation runs in its own session and commits atomically, so a crash
    between operations never leaves a half-updated claim.
    """

    def __init__(self, session_factory: Callable[[], Session], workflow_id: str = "workflow"):
        self._session_factory = session_factory
        self.workflow_id = workflow_id

    def _row_id(self, session: Session, task_id: str) -> str | None:
        row = session.execute(
            select(WorkflowTaskRecord.id).where(
                WorkflowTaskRecord.workflow_id == self.workflow_id,
                WorkflowTaskRecord.task_key == task_id,
            )
        ).scalar_one_or_none()
        return None if row is None else str(row)

    def _session(self) -> Session:
        return self._session_factory()

    def register(self, specs: Sequence[TaskSpec]) -> None:
        session = self._session()
        try:
            for spec in specs:
                session.add(
                    WorkflowTaskRecord(
                        id=uuid.uuid4().hex,
                        workflow_id=self.workflow_id,
                        task_key=spec.task_id,
                        status=TaskStatus.PENDING.value,
                        attempts=0,
                        max_attempts=spec.max_attempts or 1,
                        payload_json=dict(spec.payload),
                    )
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def claim(self, task_id: str, worker_id: str) -> Claim | None:
        session = self._session()
        try:
            row_id = self._row_id(session, task_id)
            if row_id is None:
                session.rollback()
                return None
            stored = claims_api.claim_task(session, row_id, worker_id)
            session.commit()
            if stored is None:
                return None
            # Remap to the logical task id: the claims layer works with row
            # primary keys, the scheduler works with plan task ids.
            return Claim(
                task_id=task_id,
                claim_token=stored.claim_token,
                worker_id=stored.worker_id,
                attempts=stored.attempts,
            )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def succeed(self, claim: Claim, result: Any) -> None:
        self._complete(claim, TaskStatus.SUCCEEDED, result=result)

    def fail(self, claim: Claim, error: str, *, requeue: bool) -> None:
        session = self._session()
        try:
            row_id = self._row_id(session, claim.task_id)
            if row_id is None:
                raise ClaimConflictError(f"unknown task {claim.task_id!r}")
            claims_api.release_claim(
                session, row_id, claim.claim_token, error=error, requeue=requeue
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _complete(self, claim: Claim, status: TaskStatus, *, result: Any = None) -> None:
        session = self._session()
        try:
            row_id = self._row_id(session, claim.task_id)
            if row_id is None:
                raise ClaimConflictError(f"unknown task {claim.task_id!r}")
            claims_api.complete_claim(
                session, row_id, claim.claim_token, status=status, result=result
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def cancel(self, task_id: str, reason: str) -> None:
        session = self._session()
        try:
            row_id = self._row_id(session, task_id)
            if row_id is not None:
                claims_api.cancel_task(session, row_id, reason=reason)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
