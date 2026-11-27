"""Tool Registry and Tool Gateway routes (SPEC §6 Phase 2 item 7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import CurrentAuth, CurrentSession, require
from app.models.enums import AutonomyLevel
from app.schemas.runs import ToolInvokeRequest, ToolInvokeResult, ToolOut
from app.services import system_service, tool_service

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=list[ToolOut], summary="List registered tools")
async def list_tools(auth: CurrentAuth, session: CurrentSession) -> list[ToolOut]:
    auth.require("tools:read")
    rows = await tool_service.list_tools(session, auth.organization_id)
    return [ToolOut.model_validate(row) for row in rows]


@router.post(
    "/sync-builtin",
    response_model=list[ToolOut],
    summary="Register the built-in safe tools for this organization",
    dependencies=[Depends(require("tools:write"))],
)
async def sync_builtin(auth: CurrentAuth, session: CurrentSession) -> list[ToolOut]:
    await tool_service.ensure_builtin_tools(session, auth.organization_id)
    rows = await tool_service.list_tools(session, auth.organization_id)
    await session.commit()
    return [ToolOut.model_validate(row) for row in rows]


@router.post(
    "/invoke", response_model=ToolInvokeResult, summary="Invoke a tool through the gateway"
)
async def invoke(
    payload: ToolInvokeRequest, auth: CurrentAuth, session: CurrentSession
) -> ToolInvokeResult:
    """Every call is audited; allow/ask/deny comes from the action policy."""
    auth.require("tools:invoke")
    level = AutonomyLevel(auth.organization.autonomy_level)
    rules = await system_service.get_policy(session, auth.organization, level)
    result = await tool_service.invoke_tool(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        tool_slug=payload.tool_slug,
        arguments=payload.arguments,
        run_id=payload.run_id,
        agent_id=payload.agent_id,
        autonomy_level=level,
        policy_rules=rules,
    )
    await session.commit()
    return ToolInvokeResult(**result)
