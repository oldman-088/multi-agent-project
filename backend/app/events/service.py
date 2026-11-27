"""Event append service — the outbox writer (docs/SPEC.md §4.3, §7).

``append_event`` assigns the next ``sequence`` for the target stream and
inserts the row. Callers invoke it INSIDE the same transaction as the state
change it records, then commit once. ``sequence`` is monotonic per run; the
``uq_events_run_sequence`` unique constraint is the cross-process backstop.
Global events (run_id=None, e.g. emergency stop) use the global (NULL)
stream.

Sequence allocation is safe because every SQLite transaction on this engine
starts with ``BEGIN IMMEDIATE`` (see ``backend.app.core.db``): the writer
lock is held from transaction start, so the ``MAX(sequence)`` read and the
``INSERT`` are atomic with respect to every other writer, and no in-process
lock is needed (an application-level lock here would deadlock against the
database write lock).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Event, redacted


async def next_sequence(session: AsyncSession, run_id: str | None) -> int:
    """Return MAX(sequence)+1 for the stream (NULL run_id = global stream).

    Must be called inside the same (already-locked, IMMEDIATE) transaction
    that inserts the event.
    """
    stmt = select(func.max(Event.sequence)).where(Event.run_id == run_id)
    current = await session.scalar(stmt)
    return (current or 0) + 1


async def append_event(
    session: AsyncSession,
    *,
    organization_id: str,
    event_type: str,
    run_id: str | None = None,
    task_id: str | None = None,
    agent_id: str | None = None,
    correlation_id: str | None = None,
    source_runtime: str = "native",
    payload: dict[str, Any] | None = None,
    event_version: int = 1,
) -> Event:
    """Insert one event with the next sequence in its stream (no commit)."""
    sequence = await next_sequence(session, run_id)
    event = Event(
        organization_id=organization_id,
        run_id=run_id,
        task_id=task_id,
        agent_id=agent_id,
        correlation_id=correlation_id,
        sequence=sequence,
        event_type=event_type,
        source_runtime=source_runtime,
        payload=redacted(payload),
        event_version=event_version,
    )
    session.add(event)
    await session.flush()
    return event


__all__ = ["append_event", "next_sequence"]
