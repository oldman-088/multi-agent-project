"""Runs, events, checkpoints, approvals and the kill switch."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.auth.dependencies import CurrentAuth, CurrentSession, require
from app.models.enums import ApprovalStatus, RunStatus
from app.schemas.common import OkResponse, Page
from app.schemas.runs import (
    ApprovalDecision,
    ApprovalOut,
    CheckpointOut,
    EventOut,
    RunCreate,
    RunDetail,
    RunOut,
)
from app.services import (
    agent_service,
    approval_service,
    event_service,
    run_service,
    system_service,
)

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post(
    "",
    response_model=RunOut,
    status_code=status.HTTP_201_CREATED,
    summary="Start a run (idempotent with idempotency_key)",
    dependencies=[Depends(require("runs:write"))],
)
async def create_run(payload: RunCreate, auth: CurrentAuth, session: CurrentSession) -> RunOut:
    await system_service.ensure_not_stopped(auth.organization)
    if payload.conversation_id:
        await agent_service.get_conversation(session, auth.organization_id, payload.conversation_id)
    run, created = await run_service.create_run(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        agent_id=payload.agent_id,
        directive=payload.directive,
        conversation_id=payload.conversation_id,
        trigger=payload.trigger,
        idempotency_key=payload.idempotency_key,
    )
    await session.commit()
    if not created:
        # The response is identical for a repeated key: no duplicate work happened.
        return RunOut.model_validate(run)
    return RunOut.model_validate(run)


@router.get("", response_model=Page[RunOut], summary="List runs")
async def list_runs(
    auth: CurrentAuth,
    session: CurrentSession,
    status_filter: Annotated[RunStatus | None, Query(alias="status")] = None,
    agent_id: str | None = Query(default=None),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RunOut]:
    auth.require("runs:read")
    rows, total = await run_service.list_runs(
        session,
        auth.organization_id,
        status=status_filter,
        agent_id=agent_id,
        limit=limit,
        offset=offset,
    )
    return Page(
        items=[RunOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{run_id}", response_model=RunDetail, summary="Run detail with checkpoint and approval counts"
)
async def get_run(run_id: str, auth: CurrentAuth, session: CurrentSession) -> RunDetail:
    auth.require("runs:read")
    run = await run_service.get_run(session, auth.organization_id, run_id)
    checkpoint = await run_service.latest_checkpoint(session, run.id)
    detail = RunDetail.model_validate(run)
    detail.latest_checkpoint_step = checkpoint.step if checkpoint else None
    detail.pending_approvals = await run_service.pending_approvals(session, run.id)
    return detail


@router.post(
    "/{run_id}/start", response_model=RunOut, summary="Transition a created run to running"
)
async def start_run(run_id: str, auth: CurrentAuth, session: CurrentSession) -> RunOut:
    auth.require("runs:write")
    await system_service.ensure_not_stopped(auth.organization)
    run = await run_service.get_run(session, auth.organization_id, run_id)
    run = await run_service.transition(
        session, run=run, new_status=RunStatus.RUNNING, actor_id=auth.user.id
    )
    await session.commit()
    return RunOut.model_validate(run)


@router.post("/{run_id}/pause", response_model=RunOut, summary="Pause a running run")
async def pause_run(run_id: str, auth: CurrentAuth, session: CurrentSession) -> RunOut:
    auth.require("runs:write")
    run = await run_service.pause_run(
        session, organization_id=auth.organization_id, run_id=run_id, actor_id=auth.user.id
    )
    await session.commit()
    return RunOut.model_validate(run)


@router.post("/{run_id}/resume", response_model=RunOut, summary="Resume from the latest checkpoint")
async def resume_run(run_id: str, auth: CurrentAuth, session: CurrentSession) -> RunOut:
    auth.require("runs:write")
    await system_service.ensure_not_stopped(auth.organization)
    run = await run_service.resume_run(
        session, organization_id=auth.organization_id, run_id=run_id, actor_id=auth.user.id
    )
    await session.commit()
    return RunOut.model_validate(run)


@router.post("/{run_id}/cancel", response_model=RunOut, summary="Cancel a run")
async def cancel_run(run_id: str, auth: CurrentAuth, session: CurrentSession) -> RunOut:
    auth.require("runs:cancel")
    run = await run_service.cancel_run(
        session, organization_id=auth.organization_id, run_id=run_id, actor_id=auth.user.id
    )
    await session.commit()
    return RunOut.model_validate(run)


@router.post("/{run_id}/complete", response_model=RunOut, summary="Mark a run as completed")
async def complete_run(run_id: str, auth: CurrentAuth, session: CurrentSession) -> RunOut:
    auth.require("runs:write")
    run = await run_service.get_run(session, auth.organization_id, run_id)
    run = await run_service.transition(
        session, run=run, new_status=RunStatus.COMPLETED, actor_id=auth.user.id
    )
    await session.commit()
    return RunOut.model_validate(run)


@router.post(
    "/{run_id}/checkpoints",
    response_model=CheckpointOut,
    status_code=status.HTTP_201_CREATED,
    summary="Persist a checkpoint for resume",
)
async def create_checkpoint(
    run_id: str,
    auth: CurrentAuth,
    session: CurrentSession,
    step: Annotated[int, Query(ge=1, le=100_000)],
    label: str = Query(default="", max_length=120),
    state: dict | None = None,
) -> CheckpointOut:
    auth.require("runs:write")
    checkpoint = await run_service.create_checkpoint(
        session,
        organization_id=auth.organization_id,
        run_id=run_id,
        step=step,
        state=state or {},
        label=label,
    )
    await session.commit()
    return CheckpointOut.model_validate(checkpoint)


@router.get(
    "/{run_id}/events", response_model=list[EventOut], summary="Events for a run (replayable)"
)
async def run_events(
    run_id: str,
    auth: CurrentAuth,
    session: CurrentSession,
    after_sequence: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[EventOut]:
    auth.require("events:read")
    run = await run_service.get_run(session, auth.organization_id, run_id)
    rows = await event_service.list_events(
        session,
        organization_id=auth.organization_id,
        run_id=run.id,
        after_sequence=after_sequence,
        limit=limit,
    )
    return [EventOut.model_validate(row, from_attributes=True) for row in rows]


events_router = APIRouter(prefix="/events", tags=["events"])


@events_router.get(
    "", response_model=list[EventOut], summary="Organization event stream (resume cursor)"
)
async def list_events(
    auth: CurrentAuth,
    session: CurrentSession,
    run_id: str | None = Query(default=None),
    after_sequence: Annotated[int | None, Query(ge=0)] = None,
    event_type: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[EventOut]:
    auth.require("events:read")
    rows = await event_service.list_events(
        session,
        organization_id=auth.organization_id,
        run_id=run_id,
        after_sequence=after_sequence,
        event_types=event_type,
        limit=limit,
    )
    return [EventOut.model_validate(row, from_attributes=True) for row in rows]


approvals_router = APIRouter(prefix="/approvals", tags=["approvals"])


@approvals_router.get("", response_model=Page[ApprovalOut], summary="Approvals inbox")
async def list_approvals(
    auth: CurrentAuth,
    session: CurrentSession,
    status_filter: Annotated[ApprovalStatus | None, Query(alias="status")] = None,
    run_id: str | None = Query(default=None),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ApprovalOut]:
    auth.require("approvals:read")
    rows, total = await approval_service.list_approvals(
        session,
        organization_id=auth.organization_id,
        status=status_filter,
        run_id=run_id,
        limit=limit,
        offset=offset,
    )
    return Page(
        items=[ApprovalOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@approvals_router.post(
    "/{approval_id}/decide", response_model=ApprovalOut, summary="Approve or reject an approval"
)
async def decide_approval(
    approval_id: str, payload: ApprovalDecision, auth: CurrentAuth, session: CurrentSession
) -> ApprovalOut:
    auth.require("approvals:write")
    approval = await approval_service.decide(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        approval_id=approval_id,
        approve=payload.approve,
        note=payload.note,
    )
    await session.commit()
    return ApprovalOut.model_validate(approval)


system_router = APIRouter(prefix="/system", tags=["system"])


@system_router.post(
    "/emergency-stop", response_model=dict, summary="Engage or clear the global kill switch"
)
async def emergency_stop(payload: dict, auth: CurrentAuth, session: CurrentSession) -> dict:
    """The kill switch is always available and can never be disabled by a level."""
    auth.require("system:write")
    engage = bool(payload.get("engage", True))
    reason = str(payload.get("reason", ""))[:400]
    result = await system_service.set_emergency_stop(
        session,
        organization=auth.organization,
        actor_id=auth.user.id,
        engage=engage,
        reason=reason,
    )
    await session.commit()
    return result


@system_router.get("/emergency-stop", response_model=dict, summary="Kill switch state")
async def emergency_stop_state(auth: CurrentAuth, session: CurrentSession) -> dict:
    return await system_service.emergency_stop_state(session, auth.organization)


@system_router.post("/ping", response_model=OkResponse, summary="Authenticated liveness probe")
async def ping(auth: CurrentAuth) -> OkResponse:
    return OkResponse(message=f"hello {auth.user.email}")
