"""Atomic task claims — portable across SQLite and PostgreSQL.

A claim is a single conditional ``UPDATE ... WHERE status = 'pending'``: both
SQLite and PostgreSQL execute that statement atomically, so exactly one of any
number of concurrent callers can flip a row from ``pending`` to ``claimed``.
The claim also stamps a random ``claim_token``; every later state change must
present the same token, which makes double-completion impossible even across
processes.

Functions never commit: the caller owns the transaction (the store wrapper in
:mod:`app.workflows.store` commits per operation).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.engine import CursorResult, Result
from sqlalchemy.orm import Session

from .errors import ClaimConflictError
from .models import WorkflowTaskRecord, utcnow
from .status import TaskStatus

_HELD_STATES = (TaskStatus.CLAIMED.value, TaskStatus.RUNNING.value)


def _rowcount(result: Result[Any]) -> int:
    """Rows changed by a DML statement (typed Result hides CursorResult)."""
    return int(cast("CursorResult[Any]", result).rowcount)


@dataclass(frozen=True, slots=True)
class Claim:
    """Proof that one worker holds one task."""

    task_id: str
    claim_token: str
    worker_id: str
    attempts: int


def claim_task(
    session: Session,
    task_id: str,
    worker_id: str,
    *,
    now: datetime | None = None,
    claim_token: str | None = None,
) -> Claim | None:
    """Atomically claim a pending task; ``None`` when it is not claimable.

    A task is claimable while it is ``pending`` and has attempts left.  The
    attempt counter is incremented as part of the same statement, so the claim
    *is* the attempt.

    Args:
        session: An open SQLAlchemy session (not committed by this function).
        task_id: Primary key of the ``workflow_tasks`` row.
        worker_id: Who claims the task (audit field).
        now: Override the claim timestamp (tests).
        claim_token: Override the generated token (tests).
    """
    if not worker_id:
        raise ValueError("worker_id must be a non-empty string")
    token = claim_token or secrets.token_hex(16)
    claimed_at = now or utcnow()
    updated = session.execute(
        sa.update(WorkflowTaskRecord)
        .where(
            WorkflowTaskRecord.id == task_id,
            WorkflowTaskRecord.status == TaskStatus.PENDING.value,
            WorkflowTaskRecord.attempts < WorkflowTaskRecord.max_attempts,
        )
        .values(
            status=TaskStatus.CLAIMED.value,
            claim_token=token,
            claimed_by=worker_id,
            claimed_at=claimed_at,
            updated_at=claimed_at,
            attempts=WorkflowTaskRecord.attempts + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if _rowcount(updated) != 1:
        return None
    attempts = session.execute(
        sa.select(WorkflowTaskRecord.attempts).where(WorkflowTaskRecord.id == task_id)
    ).scalar_one()
    return Claim(task_id=task_id, claim_token=token, worker_id=worker_id, attempts=int(attempts))


def complete_claim(
    session: Session,
    task_id: str,
    claim_token: str,
    *,
    status: TaskStatus,
    result: object = None,
    error: str | None = None,
    now: datetime | None = None,
) -> None:
    """Complete a held task with a terminal status; only the token holder can.

    Raises:
        ClaimConflictError: The task is not held by this token (already
            completed, released, or claimed by someone else).
        ValueError: ``status`` is not terminal.
    """
    if status not in (TaskStatus.SUCCEEDED, TaskStatus.FAILED):
        raise ValueError(f"complete_claim needs a terminal status, got {status!r}")
    values: dict[str, object] = {
        "status": status.value,
        "claim_token": None,
        "updated_at": now or utcnow(),
    }
    if status is TaskStatus.SUCCEEDED:
        values["result_json"] = result
        values["error"] = None
    else:
        values["error"] = error
    updated = session.execute(
        sa.update(WorkflowTaskRecord)
        .where(
            WorkflowTaskRecord.id == task_id,
            WorkflowTaskRecord.claim_token == claim_token,
            WorkflowTaskRecord.status.in_(_HELD_STATES),
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if _rowcount(updated) != 1:
        raise ClaimConflictError(
            f"task {task_id!r} is not held by this claim (already completed or released)"
        )


def release_claim(
    session: Session,
    task_id: str,
    claim_token: str,
    *,
    error: str | None = None,
    requeue: bool = True,
    now: datetime | None = None,
) -> TaskStatus:
    """Release a held task after a failed attempt.

    With ``requeue=True`` the task goes back to ``pending`` while attempts
    remain, otherwise it is marked ``failed``.  Returns the new status.

    Raises:
        ClaimConflictError: The task is not held by this token.
    """
    row = session.execute(
        sa.select(WorkflowTaskRecord.attempts, WorkflowTaskRecord.max_attempts).where(
            WorkflowTaskRecord.id == task_id,
            WorkflowTaskRecord.claim_token == claim_token,
            WorkflowTaskRecord.status.in_(_HELD_STATES),
        )
    ).one_or_none()
    if row is None:
        raise ClaimConflictError(f"task {task_id!r} is not held by this claim")
    attempts, max_attempts = int(row[0]), int(row[1])
    new_status = TaskStatus.PENDING if requeue and attempts < max_attempts else TaskStatus.FAILED
    updated = session.execute(
        sa.update(WorkflowTaskRecord)
        .where(
            WorkflowTaskRecord.id == task_id,
            WorkflowTaskRecord.claim_token == claim_token,
            WorkflowTaskRecord.status.in_(_HELD_STATES),
        )
        .values(
            status=new_status.value,
            claim_token=None,
            error=error,
            updated_at=now or utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    if _rowcount(updated) != 1:
        raise ClaimConflictError(f"task {task_id!r} is not held by this claim")
    return new_status


def cancel_task(
    session: Session,
    task_id: str,
    *,
    reason: str,
    now: datetime | None = None,
) -> bool:
    """Cancel an unclaimed (``pending``) task; returns whether it was cancelled."""
    updated = session.execute(
        sa.update(WorkflowTaskRecord)
        .where(
            WorkflowTaskRecord.id == task_id,
            WorkflowTaskRecord.status == TaskStatus.PENDING.value,
        )
        .values(
            status=TaskStatus.CANCELLED.value,
            error=reason,
            updated_at=now or utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    return _rowcount(updated) == 1
