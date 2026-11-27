"""Run lifecycle, checkpoints and resume (SPEC §4.3, §7, §13.3)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.core.security import new_id
from app.db.base import utcnow
from app.models.agents import AgentVersion
from app.models.enums import RunStatus, RunTrigger
from app.models.runs import Approval, Checkpoint, Run
from app.services import audit, event_service
from app.services.agent_service import get_agent

#: Legal state transitions. Anything else is a 409 rather than a silent overwrite.
ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.CREATED: frozenset(
        {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.PAUSED}
    ),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.PAUSED,
            RunStatus.WAITING_FOR_USER,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.PAUSED: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED}),
    RunStatus.WAITING_FOR_USER: frozenset(
        {RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED}
    ),
    RunStatus.RESUME_AVAILABLE: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset({RunStatus.RESUME_AVAILABLE}),
    RunStatus.CANCELLED: frozenset(),
}


async def create_run(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    agent_id: str,
    directive: str,
    conversation_id: str | None = None,
    trigger: RunTrigger = RunTrigger.MANUAL,
    idempotency_key: str | None = None,
) -> tuple[Run, bool]:
    """Create a run. Returns ``(run, created)``; a repeat key returns the original."""
    if idempotency_key:
        existing = await session.scalar(
            select(Run).where(
                Run.organization_id == organization_id,
                Run.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing, False

    agent = await get_agent(session, organization_id, agent_id)
    if not agent.is_enabled:
        raise ConflictError("Agent is disabled", code="agent_disabled")

    version = await session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id, AgentVersion.version == agent.current_version
        )
    )

    run = Run(
        organization_id=organization_id,
        agent_id=agent.id,
        agent_version_id=version.id if version else None,
        conversation_id=conversation_id,
        connection_id=agent.connection_id,
        status=RunStatus.CREATED,
        trigger=trigger,
        directive=directive,
        idempotency_key=idempotency_key,
    )
    session.add(run)
    await session.flush()
    await event_service.append_event(
        session,
        organization_id=organization_id,
        run_id=run.id,
        agent_id=agent.id,
        event_type="run.created",
        payload={
            "agent_id": agent.id,
            "agent_version": agent.current_version,
            "trigger": str(trigger),
            "directive_length": len(directive),
        },
    )
    await audit.record(
        session,
        action="runs.create",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="run",
        target_id=run.id,
        context={"agent_id": agent.id, "trigger": str(trigger)},
    )
    return run, True


async def get_run(session: AsyncSession, organization_id: str, run_id: str) -> Run:
    run = await session.get(Run, run_id)
    if run is None or run.organization_id != organization_id:
        raise NotFoundError("Run not found", details={"run_id": run_id})
    return run


async def list_runs(
    session: AsyncSession,
    organization_id: str,
    *,
    status: RunStatus | None = None,
    agent_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Run], int]:
    conditions = [Run.organization_id == organization_id]
    if status is not None:
        conditions.append(Run.status == status)
    if agent_id is not None:
        conditions.append(Run.agent_id == agent_id)
    total = await session.scalar(select(func.count()).select_from(Run).where(*conditions))
    rows = (
        await session.scalars(
            select(Run)
            .where(*conditions)
            .order_by(Run.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(rows), int(total or 0)


async def transition(
    session: AsyncSession,
    *,
    run: Run,
    new_status: RunStatus,
    actor_id: str | None = None,
    error: str | None = None,
) -> Run:
    """Move a run to ``new_status`` and emit the matching event."""
    current = RunStatus(run.status)
    if new_status == current:
        return run
    if new_status not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise ConflictError(
            f"Illegal run transition {current.value} -> {new_status.value}",
            code="illegal_transition",
        )
    run.status = new_status
    now = utcnow()
    if new_status is RunStatus.RUNNING and run.started_at is None:
        run.started_at = now
    if new_status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
        run.finished_at = now
    if error:
        run.error = error[:600]

    event_map = {
        RunStatus.RUNNING: "run.started",
        RunStatus.PAUSED: "run.paused",
        RunStatus.WAITING_FOR_USER: "agent.waiting",
        RunStatus.COMPLETED: "run.completed",
        RunStatus.FAILED: "run.failed",
        RunStatus.CANCELLED: "run.cancelled",
    }
    event_type = event_map.get(new_status)
    if event_type:
        await event_service.append_event(
            session,
            organization_id=run.organization_id,
            run_id=run.id,
            agent_id=run.agent_id,
            event_type=event_type,
            payload={"from": current.value, "to": new_status.value, "error": error},
        )
    await audit.record(
        session,
        action=f"runs.{new_status.value}",
        actor_id=actor_id,
        organization_id=run.organization_id,
        target_type="run",
        target_id=run.id,
        context={"from": current.value, "to": new_status.value},
    )
    return run


async def cancel_run(
    session: AsyncSession, *, organization_id: str, run_id: str, actor_id: str
) -> Run:
    run = await get_run(session, organization_id, run_id)
    return await transition(session, run=run, new_status=RunStatus.CANCELLED, actor_id=actor_id)


async def pause_run(
    session: AsyncSession, *, organization_id: str, run_id: str, actor_id: str
) -> Run:
    run = await get_run(session, organization_id, run_id)
    return await transition(session, run=run, new_status=RunStatus.PAUSED, actor_id=actor_id)


async def resume_run(
    session: AsyncSession, *, organization_id: str, run_id: str, actor_id: str
) -> Run:
    """Resume from the latest checkpoint (SPEC §13.3 restart behaviour)."""
    run = await get_run(session, organization_id, run_id)
    checkpoint = await latest_checkpoint(session, run.id)
    if checkpoint is None and RunStatus(run.status) in {
        RunStatus.PAUSED,
        RunStatus.WAITING_FOR_USER,
    }:
        # Allowed without a checkpoint: nothing had been persisted yet.
        checkpoint = None
    run = await transition(session, run=run, new_status=RunStatus.RUNNING, actor_id=actor_id)
    await event_service.append_event(
        session,
        organization_id=organization_id,
        run_id=run.id,
        agent_id=run.agent_id,
        event_type="run.resumed",
        payload={"from_checkpoint": checkpoint.step if checkpoint else None},
    )
    return run


async def create_checkpoint(
    session: AsyncSession,
    *,
    organization_id: str,
    run_id: str,
    step: int,
    state: dict,
    label: str = "",
    resumable: bool = True,
) -> Checkpoint:
    run = await get_run(session, organization_id, run_id)
    checkpoint = Checkpoint(
        id=new_id("ckp"),
        organization_id=organization_id,
        run_id=run.id,
        step=step,
        label=label,
        state=state,
        resumable=resumable,
    )
    session.add(checkpoint)
    run.step_count = max(run.step_count, step)
    await session.flush()
    await event_service.append_event(
        session,
        organization_id=organization_id,
        run_id=run.id,
        agent_id=run.agent_id,
        event_type="checkpoint.created",
        payload={"step": step, "label": label, "resumable": resumable},
    )
    return checkpoint


async def latest_checkpoint(session: AsyncSession, run_id: str) -> Checkpoint | None:
    return await session.scalar(
        select(Checkpoint)
        .where(Checkpoint.run_id == run_id)
        .order_by(Checkpoint.step.desc())
        .limit(1)
    )


async def pending_approvals(session: AsyncSession, run_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Approval)
            .where(Approval.run_id == run_id, Approval.status == "pending")
        )
        or 0
    )
