"""Approval inbox: request, decide, expire (SPEC §8.3-H, §1 step 7)."""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.core.errors import ConflictError, NotFoundError
from app.db.base import utcnow
from app.models.agents import Agent
from app.models.enums import ApprovalStatus
from app.models.runs import Approval
from app.services import audit, event_service


async def request_approval(
    session: AsyncSession,
    *,
    organization_id: str,
    kind: str,
    reason: str,
    run_id: str | None = None,
    agent_id: str | None = None,
    tool_slug: str | None = None,
    payload: dict | None = None,
) -> Approval:
    approval = Approval(
        organization_id=organization_id,
        kind=kind,
        status=ApprovalStatus.PENDING,
        run_id=run_id,
        agent_id=agent_id,
        tool_slug=tool_slug,
        requested_payload=payload or {},
        reason=reason[:600],
    )
    session.add(approval)
    await session.flush()
    await event_service.append_event(
        session,
        organization_id=organization_id,
        run_id=run_id,
        agent_id=agent_id,
        event_type="approval.requested",
        payload={"approval_id": approval.id, "kind": kind, "reason": reason[:200]},
    )
    return approval


async def list_approvals(
    session: AsyncSession,
    *,
    organization_id: str,
    status: ApprovalStatus | None = None,
    run_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Approval], int]:
    conditions = [Approval.organization_id == organization_id]
    if status is not None:
        conditions.append(Approval.status == status)
    if run_id is not None:
        conditions.append(Approval.run_id == run_id)
    total = await session.scalar(select(func.count()).select_from(Approval).where(*conditions))
    rows = (
        await session.scalars(
            select(Approval)
            .where(*conditions)
            .order_by(Approval.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(rows), int(total or 0)


async def decide(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    approval_id: str,
    approve: bool,
    note: str = "",
) -> Approval:
    """A human decides. An AI actor can never approve: ``actor_type`` is a user.

    The pending check and the write happen in one atomic ``UPDATE ... WHERE
    status = 'pending'``. A read-then-write let two concurrent decisions both see
    ``pending`` and both succeed, writing an approved *and* a rejected event for
    the same approval; an approval is now decided exactly once.
    """
    approval = await session.get(Approval, approval_id)
    if approval is None or approval.organization_id != organization_id:
        raise NotFoundError("Approval not found")
    if ApprovalStatus(approval.status) is not ApprovalStatus.PENDING:
        raise ConflictError(f"Approval is already '{approval.status}'", code="approval_not_pending")

    target = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    decided_at = utcnow()
    claimed = await session.scalar(
        update(Approval)
        .where(Approval.id == approval.id, Approval.status == ApprovalStatus.PENDING)
        .values(
            status=target,
            decided_by=actor_id,
            decided_at=decided_at,
            decision_note=note[:600],
        )
        .returning(Approval.id)
        .execution_options(synchronize_session=False)
    )
    if claimed is None:
        # Another request decided it between the check and the update.
        raise ConflictError("Approval was decided by another request", code="approval_not_pending")
    # Mirror the claimed row onto the loaded instance (see run_service.transition).
    set_committed_value(approval, "status", target)
    set_committed_value(approval, "decided_by", actor_id)
    set_committed_value(approval, "decided_at", decided_at)
    set_committed_value(approval, "decision_note", note[:600])
    await event_service.append_event(
        session,
        organization_id=organization_id,
        run_id=approval.run_id,
        agent_id=approval.agent_id,
        event_type="approval.approved" if approve else "approval.rejected",
        payload={"approval_id": approval.id, "note": note[:200]},
    )
    await audit.record(
        session,
        action="approvals.decide",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="approval",
        target_id=approval.id,
        context={"approve": approve, "kind": str(approval.kind)},
    )
    return approval


async def require_human_merge_approval(
    session: AsyncSession, *, organization_id: str, approval_id: str
) -> Approval:
    approval = await session.get(Approval, approval_id)
    if (
        approval is None
        or approval.organization_id != organization_id
        or ApprovalStatus(approval.status) is not ApprovalStatus.APPROVED
        or approval.kind != "merge"
    ):
        raise ConflictError(
            "A human-approved merge approval is required", code="human_approval_required"
        )
    return approval


async def agent_name(session: AsyncSession, agent_id: str | None) -> str | None:
    if not agent_id:
        return None
    agent = await session.get(Agent, agent_id)
    return agent.name if agent else None
