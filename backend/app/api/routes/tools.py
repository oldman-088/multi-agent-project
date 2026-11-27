"""Tool Gateway and approvals API (docs/SPEC.md §3.2, §13.2).

- ``GET  /api/tools``                        — the registry (schemas included).
- ``POST /api/runs/{run_id}/tool-calls``     — submit a call through the gateway.
- ``GET  /api/tool-calls``                   — the audit trail (org-scoped).
- ``GET  /api/approvals`` / approve / reject — human decisions for ``ask``.

Approving or rejecting requires admin or owner; members can submit calls and
view the audit trail; viewers are read-only. Every gateway decision — allow,
ask or deny — is audited (§3.2 "always audits"). While the emergency stop is
engaged, submissions and approvals return 409.
"""

from __future__ import annotations

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
from backend.app.models import Approval, Run, ToolCall, User, utcnow
from backend.app.schemas import (
    ApprovalOut,
    ToolCallOut,
    ToolCallRequest,
    ToolSpecOut,
    ToolsResponse,
)
from backend.app.tools.builtins import TOOL_SPECS
from backend.app.tools.gateway import execute_approved, submit_tool_call

router = APIRouter(tags=["tools"])


async def _ensure_not_engaged(session: AsyncSession) -> None:
    from backend.app.models import EmergencyStop

    stop = await session.get(EmergencyStop, 1)
    if stop is not None and stop.engaged:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Emergency stop is engaged; tool calls are blocked until cleared",
        )


def _require_decision_roles(user: User) -> None:
    if user.role not in ("owner", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")


@router.get("/api/tools", response_model=ToolsResponse)
async def list_tools(_user: Annotated[User, Depends(get_current_user)]) -> ToolsResponse:
    """List registered tools with their JSON Schema (auth required)."""
    return ToolsResponse(
        tools=[
            ToolSpecOut(
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
                requires_approval=spec.requires_approval,
            )
            for spec in TOOL_SPECS.values()
        ]
    )


@router.post(
    "/api/runs/{run_id}/tool-calls",
    response_model=ToolCallOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_tool_call(
    run_id: str,
    payload: ToolCallRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ToolCallOut:
    """Submit a tool call for a running run; the gateway decides allow/ask/deny.

    Unknown tools → 404 and invalid arguments → 422 (both still audited as
    ``deny`` rows); denied calls return 201 with the persisted audit record.
    """
    if user.role not in ("owner", "admin", "member"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    await _ensure_not_engaged(session)
    run = await get_org_run_or_404(session, run_id, user)
    if run.status != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run is not active (status '{run.status}')",
        )
    tool_call, decision = await submit_tool_call(
        session,
        settings,
        run=run,
        user=user,
        tool_name=payload.tool,
        arguments=payload.arguments,
    )
    if decision.error_code == "unknown_tool":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown tool")
    if decision.error_code == "invalid_arguments":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Tool arguments failed JSON Schema validation",
        )
    await session.refresh(tool_call)
    return ToolCallOut.model_validate(tool_call)


@router.get("/api/tool-calls", response_model=list[ToolCallOut])
async def list_tool_calls(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    run_id: Annotated[str | None, Query(max_length=64)] = None,
    call_status: Annotated[str | None, Query(max_length=24)] = None,
) -> list[ToolCallOut]:
    """The org-scoped Tool Gateway audit trail."""
    stmt = select(ToolCall).where(ToolCall.organization_id == user.organization_id)
    if run_id is not None:
        stmt = stmt.where(ToolCall.run_id == run_id)
    if call_status is not None:
        stmt = stmt.where(ToolCall.status == call_status)
    rows = await session.scalars(stmt.order_by(ToolCall.created_at, ToolCall.id))
    return [ToolCallOut.model_validate(row) for row in rows]


async def _org_approval_or_404(session: AsyncSession, approval_id: str, user: User) -> Approval:
    approval = await session.get(Approval, approval_id)
    if approval is None or approval.organization_id != user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return approval


@router.get("/api/approvals", response_model=list[ApprovalOut])
async def list_approvals(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    approval_status: Annotated[str | None, Query(max_length=16)] = None,
    run_id: Annotated[str | None, Query(max_length=64)] = None,
) -> list[ApprovalOut]:
    """The approvals inbox (org-scoped; readable by every role)."""
    stmt = select(Approval).where(Approval.organization_id == user.organization_id)
    if approval_status is not None:
        stmt = stmt.where(Approval.status == approval_status)
    if run_id is not None:
        stmt = stmt.where(Approval.run_id == run_id)
    rows = await session.scalars(stmt.order_by(Approval.created_at, Approval.id))
    return [ApprovalOut.model_validate(row) for row in rows]


@router.get("/api/approvals/{approval_id}", response_model=ApprovalOut)
async def get_approval(
    approval_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ApprovalOut:
    approval = await _org_approval_or_404(session, approval_id, user)
    return ApprovalOut.model_validate(approval)


async def _decide_approval(
    session: AsyncSession,
    settings: Settings,
    approval_id: str,
    user: User,
    *,
    approve: bool,
) -> ApprovalOut:
    _require_decision_roles(user)
    approval = await _org_approval_or_404(session, approval_id, user)
    if approval.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Approval already decided (status '{approval.status}')",
        )
    await _ensure_not_engaged(session)
    tool_call = await session.get(ToolCall, approval.tool_call_id)
    run = await session.get(Run, approval.run_id)
    if tool_call is None or run is None:  # pragma: no cover — referential integrity
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval target missing")
    if run.status != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run is not active (status '{run.status}')",
        )

    approval.decided_by = user.id
    approval.decided_at = utcnow()
    if approve:
        approval.status = "approved"
        await append_event(
            session,
            organization_id=run.organization_id,
            run_id=run.id,
            agent_id=run.agent_id,
            correlation_id=run.correlation_id,
            event_type="approval.approved",
            payload={
                "approval_id": approval.id,
                "tool_call_id": tool_call.id,
                "tool": tool_call.tool,
                "decided_by": user.id,
            },
        )
        await execute_approved(session, settings, tool_call, run, decided_by=user.id)
    else:
        approval.status = "rejected"
        tool_call.status = "rejected"
        tool_call.decided_by = user.id
        tool_call.completed_at = utcnow()
        await append_event(
            session,
            organization_id=run.organization_id,
            run_id=run.id,
            agent_id=run.agent_id,
            correlation_id=run.correlation_id,
            event_type="approval.rejected",
            payload={
                "approval_id": approval.id,
                "tool_call_id": tool_call.id,
                "tool": tool_call.tool,
                "decided_by": user.id,
            },
        )
        await session.commit()
    await session.refresh(approval)
    return ApprovalOut.model_validate(approval)


@router.post("/api/approvals/{approval_id}/approve", response_model=ApprovalOut)
async def approve(
    approval_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ApprovalOut:
    """Approve a pending ``ask`` decision; the tool executes immediately."""
    return await _decide_approval(session, settings, approval_id, user, approve=True)


@router.post("/api/approvals/{approval_id}/reject", response_model=ApprovalOut)
async def reject(
    approval_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ApprovalOut:
    """Reject a pending ``ask`` decision; the tool call is marked rejected."""
    return await _decide_approval(session, settings, approval_id, user, approve=False)
