"""Run lifecycle routes with the outbox event writer (docs/SPEC.md §4.3, §7).

State machine: pending → running → completed | cancelled. Every transition
writes its event (``run.created``, ``run.started``, ``run.completed``,
``run.cancelled``) in the SAME transaction as the state change, then commits.

While the emergency stop is engaged (§3.2) no new work can start: run
creation and start return 409.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import (
    get_current_user,
    get_db,
    get_org_run_or_404,
    get_settings,
)
from backend.app.core.config import Settings
from backend.app.events.service import append_event
from backend.app.models import EmergencyStop, Event, Run, User, utcnow
from backend.app.schemas import EventOut, EventsResponse, RunCreateRequest, RunOut
from backend.app.tools.builtins import TOOL_SPECS

router = APIRouter(prefix="/api/runs", tags=["runs"])

_WRITE_ROLES = ("owner", "admin", "member")


async def _ensure_not_engaged(session: AsyncSession) -> None:
    stop = await session.get(EmergencyStop, 1)
    if stop is not None and stop.engaged:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Emergency stop is engaged; new work is blocked until cleared",
        )


def _require_write(user: User) -> None:
    if user.role not in _WRITE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")


@router.post("", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def create_run(
    payload: RunCreateRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RunOut:
    """Create a run (status ``pending``) and emit ``run.created``."""
    _require_write(user)
    await _ensure_not_engaged(session)
    if payload.allowed_tools is not None:
        unknown = [t for t in payload.allowed_tools if t not in TOOL_SPECS]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unknown tools in allowed_tools: {', '.join(sorted(unknown))}",
            )
    run = Run(
        organization_id=user.organization_id,
        created_by=user.id,
        agent_id=payload.agent_id,
        goal=payload.goal,
        autonomy_level=(
            payload.autonomy_level
            if payload.autonomy_level is not None
            else settings.autonomy_level
        ),
        allowed_tools=payload.allowed_tools,
        correlation_id=payload.correlation_id or uuid.uuid4().hex,
    )
    session.add(run)
    await session.flush()
    await append_event(
        session,
        organization_id=run.organization_id,
        run_id=run.id,
        agent_id=run.agent_id,
        correlation_id=run.correlation_id,
        event_type="run.created",
        payload={"goal": run.goal, "autonomy_level": run.autonomy_level, "created_by": user.id},
    )
    await session.commit()
    await session.refresh(run)
    return RunOut.model_validate(run)


@router.get("", response_model=list[RunOut])
async def list_runs(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[RunOut]:
    """List the caller's organization's runs (readable by every role)."""
    rows = await session.scalars(
        select(Run).where(Run.organization_id == user.organization_id).order_by(Run.created_at)
    )
    return [RunOut.model_validate(row) for row in rows]


@router.get("/{run_id}", response_model=RunOut)
async def get_run(
    run_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> RunOut:
    run = await get_org_run_or_404(session, run_id, user)
    return RunOut.model_validate(run)


@router.post("/{run_id}/start", response_model=RunOut)
async def start_run(
    run_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> RunOut:
    _require_write(user)
    await _ensure_not_engaged(session)
    run = await get_org_run_or_404(session, run_id, user)
    if run.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot start a run in status '{run.status}'",
        )
    run.status = "running"
    run.started_at = utcnow()
    await append_event(
        session,
        organization_id=run.organization_id,
        run_id=run.id,
        agent_id=run.agent_id,
        correlation_id=run.correlation_id,
        event_type="run.started",
        payload={"status": "running"},
    )
    await session.commit()
    await session.refresh(run)
    return RunOut.model_validate(run)


@router.post("/{run_id}/complete", response_model=RunOut)
async def complete_run(
    run_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> RunOut:
    _require_write(user)
    run = await get_org_run_or_404(session, run_id, user)
    if run.status != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot complete a run in status '{run.status}'",
        )
    run.status = "completed"
    run.finished_at = utcnow()
    await append_event(
        session,
        organization_id=run.organization_id,
        run_id=run.id,
        agent_id=run.agent_id,
        correlation_id=run.correlation_id,
        event_type="run.completed",
        payload={"status": "completed"},
    )
    await session.commit()
    await session.refresh(run)
    return RunOut.model_validate(run)


@router.post("/{run_id}/cancel", response_model=RunOut)
async def cancel_run(
    run_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> RunOut:
    _require_write(user)
    run = await get_org_run_or_404(session, run_id, user)
    if run.status not in ("pending", "running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel a run in status '{run.status}'",
        )
    run.status = "cancelled"
    run.finished_at = utcnow()
    await append_event(
        session,
        organization_id=run.organization_id,
        run_id=run.id,
        agent_id=run.agent_id,
        correlation_id=run.correlation_id,
        event_type="run.cancelled",
        payload={"status": "cancelled", "reason": "cancelled_by_user", "by": user.id},
    )
    await session.commit()
    await session.refresh(run)
    return RunOut.model_validate(run)


@router.get("/{run_id}/events", response_model=EventsResponse)
async def list_run_events(
    run_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    after: Annotated[int, Query(ge=-1)] = -1,
) -> EventsResponse:
    """Replay the run's events ordered by ``sequence``; ``after`` is the last
    sequence the client already has (docs/SPEC.md §4.3 reconnect replay)."""
    run = await get_org_run_or_404(session, run_id, user)
    rows = await session.scalars(
        select(Event).where(Event.run_id == run.id, Event.sequence > after).order_by(Event.sequence)
    )
    return EventsResponse(events=[EventOut.model_validate(row) for row in rows])
