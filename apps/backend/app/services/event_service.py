"""Event append and replay (SPEC §4.3, §7).

The ``events`` table is the authoritative execution history. Events are inserted
in the same transaction as the state change they describe (outbox pattern), then
published to clients. ``sequence`` is monotonic per run and doubles as the client
resume cursor.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.core.errors import ValidationFailedError
from app.core.logging import get_logger, redact
from app.core.security import new_id
from app.models.runs import Event, Run
from app.schemas.runs import EVENT_TYPES

logger = get_logger(__name__)


#: How many times an insert is retried when a concurrent writer reserved the same
#: sequence. One retry is normally enough; the loop only guards a race window.
_SEQUENCE_ATTEMPTS = 5


async def reserve_sequence(session: AsyncSession, run_id: str) -> int:
    """Reserve the next per-run sequence with one atomic statement.

    ``UPDATE ... SET last_sequence = last_sequence + 1`` is serialised by the row
    lock, so two concurrent appends for the same run can never read the same
    value (the previous read-then-write could, and the winner's unique-constraint
    violation surfaced as a 500). The counter is a high-water mark: a sequence
    reserved by a request that later rolls back is simply skipped, which keeps
    the client resume cursor safe (``after_sequence=N`` never replays).
    """
    next_value = await session.scalar(
        update(Run)
        .where(Run.id == run_id)
        .values(last_sequence=func.coalesce(Run.last_sequence, 0) + 1)
        .returning(Run.last_sequence)
        .execution_options(synchronize_session=False)
    )
    if next_value is None:
        raise ValidationFailedError("Cannot allocate a sequence for an unknown run")
    # Keep the loaded Run in step with the row so serialising the response does
    # not trigger a lazy refresh inside the request (``set_committed_value`` does
    # not mark the attribute dirty, so no second UPDATE is emitted).
    run = await session.get(Run, run_id)
    if run is not None:
        set_committed_value(run, "last_sequence", int(next_value))
    return int(next_value)


def validate_event_type(event_type: str) -> None:
    if event_type not in EVENT_TYPES:
        raise ValidationFailedError(
            f"Unknown event type '{event_type}'",
            code="unknown_event_type",
            details={"allowed": sorted(EVENT_TYPES)},
        )


async def append_event(
    session: AsyncSession,
    *,
    organization_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    run_id: str | None = None,
    task_id: str | None = None,
    agent_id: str | None = None,
    correlation_id: str | None = None,
    sequence: int | None = None,
    source_runtime: str = "native",
) -> Event:
    """Insert one event with the next per-run sequence number.

    Raises ``ValidationFailedError`` for unknown event types, so a typo can never
    silently create an event the frontend does not understand.
    """
    validate_event_type(event_type)
    sequence_explicit = sequence is not None

    if sequence is None:
        if run_id is not None:
            sequence = await reserve_sequence(session, run_id)
        else:
            sequence = (
                await session.scalar(
                    select(func.coalesce(func.max(Event.sequence), 0)).where(
                        Event.organization_id == organization_id, Event.run_id.is_(None)
                    )
                )
                or 0
            ) + 1

    event = Event(
        id=new_id("evt"),
        organization_id=organization_id,
        run_id=run_id,
        task_id=task_id,
        agent_id=agent_id,
        correlation_id=correlation_id,
        sequence=int(sequence),
        event_type=event_type,
        source_runtime=source_runtime,
        payload=redact(payload or {}),
    )

    # An explicitly supplied ``sequence`` is the caller's decision and is inserted
    # once. An allocated one is retried when another transaction won the race.
    # The retry uses a SAVEPOINT: the event insert is rolled back without touching
    # the caller's state change, which must stay in the same transaction.
    attempts = 1 if sequence_explicit else _SEQUENCE_ATTEMPTS
    for attempt in range(attempts):
        try:
            async with session.begin_nested():
                session.add(event)
                await session.flush()
            break
        except IntegrityError:
            if event in session:  # a savepoint rollback may already detach it
                session.expunge(event)
            if attempt == attempts - 1 or run_id is None:
                raise
            event.sequence = await reserve_sequence(session, run_id)
    logger.info(
        "event",
        extra={
            "extra_fields": {
                "event_type": event_type,
                "run_id": run_id,
                "sequence": event.sequence,
                "payload_keys": sorted((payload or {}).keys()),
            }
        },
    )
    return event


async def list_events(
    session: AsyncSession,
    *,
    organization_id: str,
    run_id: str | None = None,
    after_sequence: int | None = None,
    event_types: list[str] | None = None,
    limit: int = 200,
) -> list[Event]:
    """Replay events. ``after_sequence`` is the reconnect cursor."""
    conditions = [Event.organization_id == organization_id]
    if run_id is not None:
        conditions.append(Event.run_id == run_id)
    if after_sequence is not None:
        conditions.append(Event.sequence > after_sequence)
    if event_types:
        conditions.append(Event.event_type.in_(event_types))
    return list(
        (
            await session.scalars(
                select(Event)
                .where(*conditions)
                .order_by(Event.created_at, Event.sequence)
                .limit(limit)
            )
        ).all()
    )


def to_wire(event: Event) -> dict[str, Any]:
    """Serialize an event exactly as SPEC §7 describes it."""
    return {
        "event_id": event.id,
        "event_version": event.event_version,
        "organization_id": event.organization_id,
        "run_id": event.run_id,
        "task_id": event.task_id,
        "agent_id": event.agent_id,
        "correlation_id": event.correlation_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "timestamp": event.created_at.isoformat(),
        "source_runtime": event.source_runtime,
        "payload": event.payload,
    }
