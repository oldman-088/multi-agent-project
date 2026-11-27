"""System routes: health and the global emergency stop (kill switch).

docs/SPEC.md §3.2: "The kill switch (global emergency stop) is always
available in the UI, the tray icon and a global hotkey. It cannot be disabled
in any level." Here: engaging the stop cancels every active run, fans an
``emergency_stop.engaged`` event out to every organization's event feed, and
blocks new work until cleared. Engaging/clearing requires admin or owner;
the state is readable by any authenticated user. ``GET /api/health`` is the
one intentionally public route (used by startup checks and CI).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_current_user, get_db, get_settings
from backend.app.core.config import Settings
from backend.app.core.db import ping_database
from backend.app.events.service import append_event
from backend.app.models import EmergencyStop, Event, Organization, Run, User, utcnow
from backend.app.schemas import (
    EmergencyStopClearedOut,
    EmergencyStopRequest,
    EmergencyStopResultOut,
    EmergencyStopStateOut,
    EventOut,
    EventsResponse,
    HealthResponse,
)

router = APIRouter(tags=["system"])


@router.get("/api/health", response_model=HealthResponse)
async def health(
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Public liveness/readiness endpoint (no auth; startup checks rely on it)."""
    ok = await ping_database(session)
    return HealthResponse(
        status="ok" if ok else "degraded",
        app=settings.app_name,
        version=settings.version,
        database="ok" if ok else "error",
    )


async def _stop_state(session: AsyncSession) -> EmergencyStop:
    stop = await session.get(EmergencyStop, 1)
    if stop is None:
        stop = EmergencyStop(id=1, engaged=False)
        session.add(stop)
        await session.flush()
    return stop


def _require_stop_roles(user: User) -> None:
    if user.role not in ("owner", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")


@router.get("/api/system/emergency-stop", response_model=EmergencyStopStateOut)
async def get_emergency_stop(
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
) -> EmergencyStopStateOut:
    """Current kill-switch state (readable by any authenticated user)."""
    stop = await _stop_state(session)
    return EmergencyStopStateOut(
        engaged=stop.engaged,
        reason=stop.reason,
        engaged_by=stop.engaged_by,
        engaged_at=stop.engaged_at,
        cleared_by=stop.cleared_by,
        cleared_at=stop.cleared_at,
    )


@router.post("/api/system/emergency-stop", response_model=EmergencyStopResultOut)
async def engage_emergency_stop(
    payload: EmergencyStopRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> EmergencyStopResultOut:
    """Engage the global kill switch: cancel ALL active runs and block new work.

    The switch is global and available in every autonomy level (§3.2); the
    response returns only after every active run has been cancelled, which is
    what the ≤2s conformance assertion measures.
    """
    _require_stop_roles(user)
    stop = await _stop_state(session)
    if stop.engaged:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Emergency stop is already engaged"
        )

    now = utcnow()
    active_runs = (
        await session.scalars(select(Run).where(Run.status.in_(("pending", "running"))))
    ).all()
    cancelled_ids: list[str] = []
    for run in active_runs:
        run.status = "cancelled"
        run.finished_at = now
        cancelled_ids.append(run.id)
        await append_event(
            session,
            organization_id=run.organization_id,
            run_id=run.id,
            agent_id=run.agent_id,
            correlation_id=run.correlation_id,
            event_type="run.cancelled",
            payload={"status": "cancelled", "reason": "emergency_stop_engaged"},
        )

    stop.engaged = True
    stop.reason = payload.reason
    stop.engaged_by = user.id
    stop.engaged_at = now

    # Fan the engaged event out to every organization's event feed so every
    # user sees why their runs were cancelled. Global events carry run_id=NULL
    # and draw their sequence from the global (NULL) stream.
    org_ids = (await session.scalars(select(Organization.id))).all()
    for org_id in org_ids:
        await append_event(
            session,
            organization_id=org_id,
            event_type="emergency_stop.engaged",
            payload={
                "reason": payload.reason,
                "engaged_by": user.id,
                "cancelled_runs": cancelled_ids,
            },
        )
    await session.commit()
    return EmergencyStopResultOut(engaged=True, engaged_at=now, cancelled_runs=len(cancelled_ids))


@router.post("/api/system/emergency-stop/clear", response_model=EmergencyStopClearedOut)
async def clear_emergency_stop(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> EmergencyStopClearedOut:
    """Clear the kill switch; new work may start again."""
    _require_stop_roles(user)
    stop = await _stop_state(session)
    if not stop.engaged:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Emergency stop is not engaged"
        )
    now = utcnow()
    stop.engaged = False
    stop.cleared_by = user.id
    stop.cleared_at = now
    org_ids = (await session.scalars(select(Organization.id))).all()
    for org_id in org_ids:
        await append_event(
            session,
            organization_id=org_id,
            event_type="emergency_stop.cleared",
            payload={"cleared_by": user.id},
        )
    await session.commit()
    return EmergencyStopClearedOut(engaged=False, cleared_at=now)


@router.get("/api/events", response_model=EventsResponse)
async def list_events(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    after_id: Annotated[int, Query(ge=0)] = 0,
    event_type: Annotated[str | None, Query(max_length=64)] = None,
) -> EventsResponse:
    """The organization's event feed, ordered by insertion (id).

    Includes global events (``emergency_stop.*``) that were fanned out to this
    organization. ``after_id`` replays everything newer than the given row id
    (the org-feed equivalent of the per-run ``after`` sequence replay).
    """
    stmt = select(Event).where(Event.organization_id == user.organization_id, Event.id > after_id)
    if event_type is not None:
        stmt = stmt.where(Event.event_type == event_type)
    rows = await session.scalars(stmt.order_by(Event.id))
    return EventsResponse(events=[EventOut.model_validate(row) for row in rows])
