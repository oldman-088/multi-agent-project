"""The Tool Gateway (docs/SPEC.md §3.2, §13.2).

Every tool call passes through the gateway, which ALWAYS audits: allow, ask
and deny decisions all persist a :class:`~backend.app.models.ToolCall` row.

Decision order (first match wins, §13.2 action-policy semantics):

1. unknown tool                      → deny (``unknown_tool``)
2. tool not in the run's allow-list  → deny (``not_in_run_allow_list``)
3. tool-specific hard guard:
   ``http_get`` host not allow-listed → deny (``host_not_in_allowlist``)
4. arguments invalid per JSON Schema → deny (``invalid_arguments``)
5. tool flagged ``requires_approval`` → ask (``tool_requires_approval``)
6. autonomy-level policy (§13.1):
   Level 0 → ask everything; Level 1 → http_get asks, built-ins allow;
   Levels 2-3 → allow.

Deny and ask stop there. Allow executes the tool and records
``tool.execution.started`` / ``completed`` / ``failed`` events. Ask creates an
:class:`~backend.app.models.Approval` and emits ``approval.requested``;
approval/rejection is a separate human decision exposed via the approvals
API (admin and owner only).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import Settings
from backend.app.events.service import append_event
from backend.app.models import Approval, Run, ToolCall, User, redacted, utcnow
from backend.app.tools.builtins import (
    TOOL_SPECS,
    ToolExecutionError,
    ToolSpec,
    get_spec,
    validate_arguments,
)

PolicyDecision = Literal["allow", "ask", "deny"]

# Ordered action-policy defaults per autonomy level (docs/SPEC.md §13.1).
# Level 2 and Level 3 currently share the same decision table for the
# built-in tools; they diverge once the sandbox (§ Phase 5) exists — the
# difference is documented as a gap rather than faked.
LEVEL_POLICIES: dict[int, list[tuple[str, PolicyDecision]]] = {
    0: [("*", "ask")],
    1: [("http_get", "ask"), ("*", "allow")],
    2: [("*", "allow")],
    3: [("*", "allow")],
}


@dataclass(frozen=True)
class GatewayDecision:
    decision: PolicyDecision
    reason: str
    error_code: str | None = None  # set on deny: mapped to 404/422 by the API


def decide(
    spec: ToolSpec | None, run: Run, arguments: dict[str, Any], settings: Settings
) -> GatewayDecision:
    """Evaluate the gateway policy for one call (no side effects)."""
    if spec is None:
        return GatewayDecision("deny", "unknown_tool", error_code="unknown_tool")
    if run.allowed_tools is not None and spec.name not in run.allowed_tools:
        return GatewayDecision("deny", "not_in_run_allow_list")
    if spec.name == "http_get":
        from backend.app.tools.builtins import _hostname_of

        try:
            host = _hostname_of(str(arguments.get("url", "")))
        except ToolExecutionError:
            return GatewayDecision("deny", "invalid_url", error_code="invalid_arguments")
        if host.lower() not in {h.lower() for h in settings.http_get_allow_hosts}:
            return GatewayDecision("deny", "host_not_in_allowlist")
    if validate_arguments(spec, arguments):
        return GatewayDecision("deny", "invalid_arguments", error_code="invalid_arguments")
    if spec.requires_approval:
        return GatewayDecision("ask", "tool_requires_approval")
    for pattern, decision in LEVEL_POLICIES.get(run.autonomy_level, LEVEL_POLICIES[3]):
        if pattern == "*" or pattern == spec.name:
            return GatewayDecision(decision, f"level_{run.autonomy_level}_policy")
    return GatewayDecision("deny", "no_policy_match")


async def submit_tool_call(
    session: AsyncSession,
    settings: Settings,
    *,
    run: Run,
    user: User,
    tool_name: str,
    arguments: dict[str, Any],
) -> tuple[ToolCall, GatewayDecision]:
    """Run one call through the gateway and persist the outcome.

    Returns ``(tool_call, decision)``; commits transaction boundaries itself:
    the audit row + state-change events are written together (outbox).
    """
    spec = get_spec(tool_name)
    arguments = arguments if isinstance(arguments, dict) else {}
    decision = decide(spec, run, arguments, settings)

    tool_call = ToolCall(
        organization_id=user.organization_id,
        run_id=run.id,
        tool=tool_name,
        arguments=redacted(arguments),
        policy_decision=decision.decision,
        policy_reason=decision.reason,
        requested_by=user.id,
        status="pending_approval",
    )
    session.add(tool_call)
    await session.flush()

    if decision.decision == "deny":
        tool_call.status = "denied"
        await session.commit()
        return tool_call, decision

    if decision.decision == "ask":
        tool_call.status = "pending_approval"
        approval = Approval(
            organization_id=user.organization_id,
            run_id=run.id,
            tool_call_id=tool_call.id,
            requested_by=user.id,
        )
        session.add(approval)
        await session.flush()
        await append_event(
            session,
            organization_id=user.organization_id,
            run_id=run.id,
            agent_id=run.agent_id,
            correlation_id=run.correlation_id,
            event_type="approval.requested",
            payload={
                "approval_id": approval.id,
                "tool_call_id": tool_call.id,
                "tool": tool_name,
                "reason": decision.reason,
            },
        )
        await session.commit()
        return tool_call, decision

    if decision.decision == "allow":
        # An allow decision implies a registered tool (unknown tools deny).
        assert spec is not None
        await _execute_tool_call(session, settings, tool_call, spec, run, decided_by=None)
    return tool_call, decision


async def execute_approved(
    session: AsyncSession,
    settings: Settings,
    tool_call: ToolCall,
    run: Run,
    *,
    decided_by: str,
) -> ToolCall:
    """Execute a previously approved call (called by the approvals API)."""
    spec = get_spec(tool_call.tool)
    assert spec is not None  # approved calls always reference a registered tool
    tool_call.status = "executing"
    tool_call.decided_by = decided_by
    await session.flush()
    await _execute_tool_call(session, settings, tool_call, spec, run, decided_by=decided_by)
    return tool_call


async def _execute_tool_call(
    session: AsyncSession,
    settings: Settings,
    tool_call: ToolCall,
    spec: ToolSpec,
    run: Run,
    *,
    decided_by: str | None,
) -> None:
    """Execute and record started/completed/failed events (outbox commits)."""
    tool_call.status = "executing"
    tool_call.started_at = tool_call.started_at or utcnow()
    if decided_by and not tool_call.decided_by:
        tool_call.decided_by = decided_by
    await append_event(
        session,
        organization_id=run.organization_id,
        run_id=run.id,
        agent_id=run.agent_id,
        correlation_id=run.correlation_id,
        event_type="tool.execution.started",
        payload={"tool_call_id": tool_call.id, "tool": spec.name},
    )
    await session.commit()

    started = time.perf_counter()
    try:
        raw_arguments = dict(tool_call.arguments)
        result = await spec.executor(raw_arguments, settings)
    except ToolExecutionError as exc:
        tool_call.status = "failed"
        tool_call.error = str(exc)
        await append_event(
            session,
            organization_id=run.organization_id,
            run_id=run.id,
            agent_id=run.agent_id,
            correlation_id=run.correlation_id,
            event_type="tool.execution.failed",
            payload={"tool_call_id": tool_call.id, "tool": spec.name, "error": str(exc)},
        )
    else:
        tool_call.status = "completed"
        tool_call.result = redacted(result)
        await append_event(
            session,
            organization_id=run.organization_id,
            run_id=run.id,
            agent_id=run.agent_id,
            correlation_id=run.correlation_id,
            event_type="tool.execution.completed",
            payload={"tool_call_id": tool_call.id, "tool": spec.name},
        )
    tool_call.completed_at = utcnow()
    tool_call.duration_ms = round((time.perf_counter() - started) * 1000, 3)
    await session.commit()


__all__ = [
    "LEVEL_POLICIES",
    "TOOL_SPECS",
    "GatewayDecision",
    "decide",
    "execute_approved",
    "submit_tool_call",
]
