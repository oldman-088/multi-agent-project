"""Event append and replay (SPEC §4.3, §7).

The ``events`` table is the authoritative execution history. Events are inserted
in the same transaction as the state change they describe (outbox pattern), then
published to clients. ``sequence`` is monotonic per run and doubles as the client
resume cursor.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.errors import ValidationFailedError
from backend.app.core.logging import get_logger, redact
from backend.app.core.security import new_id
from backend.app.models.runs import Event, Run
from backend.app.schemas.runs import EVENT_TYPES

logger = get_logger(__name__)


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

    if sequence is None:
        if run_id is not None:
            current = await session.scalar(
                select(Run.last_sequence).where(Run.id == run_id).with_for_update()
            )
            sequence = int(current or 0) + 1
            run = await session.get(Run, run_id)
            if run is not None:
                run.last_sequence = sequence
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
    session.add(event)
    await session.flush()
    logger.info(
        "event",
        extra={
            "extra_fields": {
                "event_type": event_type,
                "run_id": run_id,
                "sequence": sequence,
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
