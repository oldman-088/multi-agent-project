"""System, autonomy, action policy, audit and dashboard routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from backend.app.auth.dependencies import CurrentAuth, CurrentSession
from backend.app.models.agents import Agent
from backend.app.models.collaboration import Mission, PullRequest
from backend.app.models.enums import ApprovalStatus, AutonomyLevel, RunStatus
from backend.app.models.identity import Organization
from backend.app.models.runs import Approval, AuditLog, Run
from backend.app.schemas.connections import (
    AutonomyOut,
    AutonomyUpdate,
    PolicyEvaluateRequest,
    PolicyEvaluateResult,
    PolicyRuleIn,
)
from backend.app.schemas.runs import AuditLogOut, EmergencyStopRequest, EmergencyStopState
from backend.app.services import policy as policy_service
from backend.app.services import system_service

router = APIRouter(prefix="/system", tags=["system"])
audit_router = APIRouter(prefix="/audit", tags=["audit"])


@router.get(
    "/autonomy", response_model=AutonomyOut, summary="Current autonomy level and kill switch"
)
async def get_autonomy(auth: CurrentAuth, session: CurrentSession) -> AutonomyOut:
    auth.require("org:read")
    state = await system_service.get_autonomy(session, auth.organization)
    return AutonomyOut(
        autonomy_level=state["autonomy_level"],
        emergency_stop_engaged=state["emergency_stop_engaged"],
    )


@router.put("/autonomy", response_model=AutonomyOut, summary="Set the autonomy level")
async def set_autonomy(
    payload: AutonomyUpdate, auth: CurrentAuth, session: CurrentSession
) -> AutonomyOut:
    auth.require("system:write")
    state = await system_service.set_autonomy(
        session,
        organization=auth.organization,
        actor_id=auth.user.id,
        level=AutonomyLevel(payload.level),
    )
    await session.commit()
    return AutonomyOut(
        autonomy_level=state["autonomy_level"],
        emergency_stop_engaged=state["emergency_stop_engaged"],
    )


@router.get(
    "/action-policy",
    response_model=list[dict],
    summary="Ordered action-policy rules for the active level",
)
async def get_policy(
    auth: CurrentAuth,
    session: CurrentSession,
    level: Annotated[AutonomyLevel | None, Query()] = None,
) -> list[dict]:
    auth.require("org:read")
    return await system_service.get_policy(session, auth.organization, level)


@router.put("/action-policy", response_model=list[dict], summary="Replace the rules for a level")
async def put_policy(
    rules: list[PolicyRuleIn],
    auth: CurrentAuth,
    session: CurrentSession,
    level: Annotated[AutonomyLevel | None, Query()] = None,
) -> list[dict]:
    auth.require("system:write")
    stored = await system_service.set_policy(
        session, organization=auth.organization, actor_id=auth.user.id, rules=rules, level=level
    )
    await session.commit()
    return stored


@router.post(
    "/action-policy/evaluate",
    response_model=PolicyEvaluateResult,
    summary="Evaluate the policy for one prospective action (first match wins)",
)
async def evaluate_policy(
    payload: PolicyEvaluateRequest, auth: CurrentAuth, session: CurrentSession
) -> PolicyEvaluateResult:
    auth.require("org:read")
    rules = await system_service.get_policy(session, auth.organization)
    decision, matched, reason = policy_service.evaluate(rules, payload)
    return PolicyEvaluateResult(decision=decision.value, matched_rule=matched, reason=reason)


@router.get("/dashboard", response_model=dict, summary="Command Center counts (real rows only)")
async def dashboard(auth: CurrentAuth, session: CurrentSession) -> dict:
    """Every number is a real count from the database. Nothing is estimated."""
    auth.require("org:read")
    org_id = auth.organization_id

    async def count(model: Any, *conditions: Any) -> int:
        return int(
            await session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
        )

    return {
        "agents_total": await count(Agent, Agent.organization_id == org_id),
        "agents_enabled": await count(
            Agent, Agent.organization_id == org_id, Agent.is_enabled.is_(True)
        ),
        "runs_total": await count(Run, Run.organization_id == org_id),
        "runs_running": await count(
            Run, Run.organization_id == org_id, Run.status == RunStatus.RUNNING
        ),
        "runs_waiting_for_user": await count(
            Run, Run.organization_id == org_id, Run.status == RunStatus.WAITING_FOR_USER
        ),
        "approvals_pending": await count(
            Approval, Approval.organization_id == org_id, Approval.status == ApprovalStatus.PENDING
        ),
        "missions_total": await count(Mission, Mission.organization_id == org_id),
        "pull_requests_open": await count(
            PullRequest, PullRequest.organization_id == org_id, PullRequest.status == "open"
        ),
        "autonomy_level": auth.organization.autonomy_level,
        "emergency_stop_engaged": (
            await system_service.emergency_stop_state(session, auth.organization)
        )["engaged"],
    }


@router.get(
    "/usage", response_model=dict, summary="Usage/cost — null unless a connection reports it"
)
async def usage(auth: CurrentAuth, session: CurrentSession) -> dict:
    """Honest reporting: token usage and cost stay null while no connection reports them."""
    auth.require("org:read")
    reported = int(
        await session.scalar(
            select(func.count()).select_from(Run).where(Run.organization_id == auth.organization_id)
        )
        or 0
    )
    return {
        "connections_reporting_usage": 0,
        "tokens": None,
        "cost": None,
        "runs_considered": reported,
        "note": "No connection reports usage yet; values are null rather than invented.",
    }


@router.get(
    "/organizations/{organization_id}", response_model=dict, summary="Organization settings"
)
async def organization_settings(
    organization_id: str, auth: CurrentAuth, session: CurrentSession
) -> dict:
    auth.require("org:read")
    if organization_id != auth.organization_id:
        from backend.app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("Not a member of this organization")
    organization = await session.get(Organization, organization_id)
    assert organization is not None
    return {
        "id": organization.id,
        "name": organization.name,
        "slug": organization.slug,
        "autonomy_level": organization.autonomy_level,
    }


@audit_router.get("", response_model=list[AuditLogOut], summary="Audit log (newest first)")
async def list_audit(
    auth: CurrentAuth,
    session: CurrentSession,
    action: str | None = Query(default=None, max_length=80),
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLogOut]:
    auth.require("audit:read")
    conditions = [AuditLog.organization_id == auth.organization_id]
    if action:
        conditions.append(AuditLog.action == action)
    rows = (
        await session.scalars(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [AuditLogOut.model_validate(row) for row in rows]


kill_switch_router = APIRouter(prefix="/kill-switch", tags=["system"])


@kill_switch_router.post(
    "", response_model=EmergencyStopState, summary="Engage or clear the kill switch"
)
async def toggle_kill_switch(
    payload: EmergencyStopRequest, auth: CurrentAuth, session: CurrentSession
) -> EmergencyStopState:
    auth.require("system:write")
    result = await system_service.set_emergency_stop(
        session,
        organization=auth.organization,
        actor_id=auth.user.id,
        engage=payload.engage,
        reason=payload.reason,
    )
    await session.commit()
    return EmergencyStopState(engaged=result["engaged"], reason=result.get("reason"))


@kill_switch_router.get("", response_model=EmergencyStopState, summary="Kill switch state")
async def kill_switch_state(auth: CurrentAuth, session: CurrentSession) -> EmergencyStopState:
    state = await system_service.emergency_stop_state(session, auth.organization)
    return EmergencyStopState(engaged=bool(state["engaged"]), reason=state.get("reason"))
