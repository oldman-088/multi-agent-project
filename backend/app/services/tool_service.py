"""Tool Registry and Tool Gateway (SPEC §6 Phase 2 item 7, §3.2).

Every tool call passes through ``invoke_tool``:
1. the tool must exist and be enabled;
2. the agent must list it in its allow-list;
3. arguments are validated against the tool's JSON Schema;
4. the action policy decides allow / ask / deny;
5. the call is audited and an event is emitted (allow and deny alike).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import jsonschema
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.errors import NotFoundError, PermissionDeniedError, ValidationFailedError
from backend.app.core.security import new_id
from backend.app.models.agents import AgentVersion
from backend.app.models.enums import AuditOutcome, AutonomyLevel, PolicyDecision
from backend.app.models.runs import Approval, ToolDefinition, ToolInvocation
from backend.app.schemas.connections import PolicyEvaluateRequest
from backend.app.services import audit, event_service
from backend.app.services import policy as policy_service

#: Safe built-in tools (SPEC §6 Phase 2 item 7). No shell, no filesystem writes.
BUILTIN_TOOLS: list[dict[str, Any]] = [
    {
        "slug": "http.get",
        "display_name": "HTTP GET",
        "description": "Fetch a URL over HTTP GET from an allow-listed host.",
        "category": "web",
        "requires_approval": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "format": "uri", "maxLength": 2000},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "slug": "calc.evaluate",
        "display_name": "Calculator",
        "description": "Evaluate a basic arithmetic expression safely.",
        "category": "utility",
        "requires_approval": False,
        "input_schema": {
            "type": "object",
            "properties": {"expression": {"type": "string", "maxLength": 200}},
            "required": ["expression"],
            "additionalProperties": False,
        },
    },
    {
        "slug": "time.now",
        "display_name": "Current time",
        "description": "Return the current UTC time and the requested IANA timezone.",
        "category": "utility",
        "requires_approval": False,
        "input_schema": {
            "type": "object",
            "properties": {"timezone": {"type": "string", "maxLength": 64}},
            "additionalProperties": False,
        },
    },
    {
        "slug": "knowledge.search",
        "display_name": "Knowledge search",
        "description": "Search the knowledge base. Returns 'not configured' until Phase 6.",
        "category": "knowledge",
        "requires_approval": False,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "maxLength": 500}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]

#: Default allow-list for HTTP GET: nothing is reachable until an owner opts in.
DEFAULT_HTTP_ALLOWLIST: frozenset[str] = frozenset({"127.0.0.1", "localhost"})


async def ensure_builtin_tools(session: AsyncSession, organization_id: str) -> list[ToolDefinition]:
    """Idempotently register the built-in tools for an organization."""
    existing = {
        row.slug: row
        for row in (
            await session.scalars(
                select(ToolDefinition).where(ToolDefinition.organization_id == organization_id)
            )
        ).all()
    }
    created: list[ToolDefinition] = []
    for spec in BUILTIN_TOOLS:
        if spec["slug"] in existing:
            continue
        tool = ToolDefinition(
            id=new_id("tol"),
            organization_id=organization_id,
            slug=spec["slug"],
            display_name=spec["display_name"],
            description=spec["description"],
            input_schema=spec["input_schema"],
            requires_approval=spec["requires_approval"],
            enabled=True,
            category=spec["category"],
        )
        session.add(tool)
        created.append(tool)
    await session.flush()
    return created


async def list_tools(session: AsyncSession, organization_id: str) -> list[ToolDefinition]:
    return list(
        (
            await session.scalars(
                select(ToolDefinition)
                .where(ToolDefinition.organization_id == organization_id)
                .order_by(ToolDefinition.slug)
            )
        ).all()
    )


async def get_tool(session: AsyncSession, organization_id: str, slug: str) -> ToolDefinition:
    row = await session.scalar(
        select(ToolDefinition).where(
            ToolDefinition.organization_id == organization_id, ToolDefinition.slug == slug
        )
    )
    if row is None:
        raise NotFoundError("Tool not found", details={"slug": slug})
    return row


def validate_arguments(tool: ToolDefinition, arguments: dict[str, Any]) -> None:
    try:
        jsonschema.validate(instance=arguments, schema=tool.input_schema or {"type": "object"})
    except jsonschema.ValidationError as exc:
        raise ValidationFailedError(
            f"Invalid arguments for tool '{tool.slug}': {exc.message}",
            code="invalid_tool_arguments",
            details={"path": list(exc.absolute_path)},
        ) from exc


async def _agent_tool_allowlist(session: AsyncSession, agent_id: str | None) -> set[str] | None:
    """``None`` means no agent context (an owner action), so skip the allow-list."""
    if not agent_id:
        return None
    from backend.app.models.agents import Agent

    agent = await session.get(Agent, agent_id)
    if agent is None:
        return set()
    version = await session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id, AgentVersion.version == agent.current_version
        )
    )
    return set(version.tools if version else [])


def _execute_builtin(
    slug: str, arguments: dict[str, Any], *, allowlist: frozenset[str]
) -> dict[str, Any]:
    """Run a built-in tool. Deliberately small and side-effect free."""
    if slug == "calc.evaluate":
        expression = str(arguments["expression"])
        allowed = set("0123456789+-*/(). %")
        if not set(expression) <= allowed:
            raise ValidationFailedError(
                "Expression contains unsupported characters", code="invalid_expression"
            )
        try:
            # ``eval`` on a character-filtered arithmetic expression only.
            value = eval(  # noqa: S307 - restricted alphabet, no names or calls
                compile(expression, "<calc>", "eval"),
                {"__builtins__": {}},
                {},
            )
        except Exception as exc:  # pragma: no cover - defensive
            raise ValidationFailedError("Invalid expression", code="invalid_expression") from exc
        return {"value": value}

    if slug == "time.now":
        tz_name = str(arguments.get("timezone") or "UTC")
        if tz_name != "UTC":
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            try:
                ZoneInfo(tz_name)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValidationFailedError("Unknown timezone", code="invalid_timezone") from exc
        return {"iso": datetime.now(UTC).isoformat(), "timezone": tz_name}

    if slug == "knowledge.search":
        # Honest placeholder: no knowledge base exists yet (SPEC §6 Phase 6).
        return {
            "configured": False,
            "results": [],
            "message": "knowledge search is not configured yet",
        }

    if slug == "http.get":
        url = str(arguments["url"])
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValidationFailedError("Only http and https are allowed", code="invalid_url")
        if parsed.hostname not in allowlist:
            raise PermissionDeniedError(
                "Host is not in the HTTP allow-list",
                code="host_not_allowed",
                details={"host": parsed.hostname},
            )
        return {"status": "not_fetched", "reason": "outbound fetch is disabled in this slice"}

    raise NotFoundError("Tool has no implementation", details={"slug": slug})


async def invoke_tool(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    tool_slug: str,
    arguments: dict[str, Any],
    run_id: str | None = None,
    agent_id: str | None = None,
    autonomy_level: AutonomyLevel = AutonomyLevel.FULL_AUTO,
    policy_rules: list[dict[str, Any]] | None = None,
    http_allowlist: frozenset[str] = DEFAULT_HTTP_ALLOWLIST,
) -> dict[str, Any]:
    """The Tool Gateway. Always audits; allow/ask/deny comes from the policy."""
    started = time.perf_counter()
    tool = await get_tool(session, organization_id, tool_slug)

    if not tool.enabled:
        raise ValidationFailedError("Tool is disabled", code="tool_disabled")

    allowlist = await _agent_tool_allowlist(session, agent_id)
    if allowlist is not None and tool.slug not in allowlist:
        await audit.record(
            session,
            action="tools.invoke",
            actor_id=actor_id,
            organization_id=organization_id,
            target_type="tool",
            target_id=tool.slug,
            outcome=AuditOutcome.DENIED,
            context={"reason": "not in agent allow-list", "agent_id": agent_id},
        )
        raise PermissionDeniedError(
            "Tool is not in this agent's allow-list",
            code="tool_not_allowed",
            details={"allowed": sorted(allowlist)},
        )

    validate_arguments(tool, arguments)

    rules = (
        policy_rules if policy_rules is not None else policy_service.default_policy(autonomy_level)
    )
    decision, matched, reason = policy_service.evaluate(
        rules,
        PolicyEvaluateRequest(tool=tool.slug, agent_id=agent_id),
    )
    if tool.requires_approval and decision is PolicyDecision.ALLOW:
        decision = PolicyDecision.ASK
        reason = "tool is flagged requires_approval"

    invocation_id = new_id("tcl")
    approval_id: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    outcome = "success"

    if decision is PolicyDecision.DENY:
        outcome = "denied"
        error = f"Denied by action policy: {reason}"
    elif decision is PolicyDecision.ASK:
        approval = Approval(
            organization_id=organization_id,
            kind="tool_call",
            status="pending",
            run_id=run_id,
            agent_id=agent_id,
            tool_slug=tool.slug,
            requested_payload={"arguments": arguments, "reason": reason},
            reason=reason,
        )
        session.add(approval)
        await session.flush()
        approval_id = approval.id
        outcome = "awaiting_approval"
        await event_service.append_event(
            session,
            organization_id=organization_id,
            run_id=run_id,
            agent_id=agent_id,
            event_type="approval.requested",
            payload={"approval_id": approval_id, "tool": tool.slug, "reason": reason},
        )
    else:
        try:
            result = _execute_builtin(tool.slug, arguments, allowlist=http_allowlist)
        except (ValidationFailedError, PermissionDeniedError) as exc:
            # Typed refusals keep their real status: a blocked host is a 403 and a
            # rejected expression is a 422, not a soft 200 with an error string.
            await audit.record(
                session,
                action="tools.invoke",
                actor_id=actor_id,
                organization_id=organization_id,
                target_type="tool",
                target_id=tool.slug,
                outcome=AuditOutcome.DENIED,
                context={
                    "decision": decision.value,
                    "code": exc.code,
                    "agent_id": agent_id,
                    "run_id": run_id,
                },
            )
            await event_service.append_event(
                session,
                organization_id=organization_id,
                run_id=run_id,
                agent_id=agent_id,
                event_type="tool.execution.failed",
                payload={"tool": tool.slug, "code": exc.code, "outcome": "denied"},
            )
            session.add(
                ToolInvocation(
                    id=invocation_id,
                    organization_id=organization_id,
                    run_id=run_id,
                    agent_id=agent_id,
                    tool_slug=tool.slug,
                    arguments=arguments,
                    decision=decision.value,
                    outcome="denied",
                    error=exc.message,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            )
            await session.commit()
            raise
        except Exception as exc:  # noqa: BLE001 - converted to a typed outcome below
            error = str(exc)
            outcome = "error"

    duration_ms = int((time.perf_counter() - started) * 1000)
    session.add(
        ToolInvocation(
            id=invocation_id,
            organization_id=organization_id,
            run_id=run_id,
            agent_id=agent_id,
            tool_slug=tool.slug,
            arguments=arguments,
            decision=decision.value,
            outcome=outcome,
            error=error,
            duration_ms=duration_ms,
        )
    )
    await event_service.append_event(
        session,
        organization_id=organization_id,
        run_id=run_id,
        agent_id=agent_id,
        event_type=(
            "tool.execution.completed"
            if outcome == "success"
            else "tool.execution.failed"
            if outcome in {"error", "denied"}
            else "tool.execution.started"
        ),
        payload={
            "tool": tool.slug,
            "decision": decision.value,
            "matched_rule": matched,
            "outcome": outcome,
            "duration_ms": duration_ms,
        },
    )
    await audit.record(
        session,
        action="tools.invoke",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="tool",
        target_id=tool.slug,
        outcome=(
            AuditOutcome.SUCCESS
            if outcome == "success"
            else AuditOutcome.DENIED
            if outcome == "denied"
            else AuditOutcome.ERROR
        ),
        context={
            "decision": decision.value,
            "reason": reason,
            "agent_id": agent_id,
            "run_id": run_id,
            "duration_ms": duration_ms,
        },
    )
    return {
        "invocation_id": invocation_id,
        "tool_slug": tool.slug,
        "decision": decision.value,
        "outcome": outcome,
        "result": result,
        "error": error,
        "approval_id": approval_id,
        "duration_ms": duration_ms,
    }
