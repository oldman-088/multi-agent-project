"""Agent CRUD with immutable versioning (SPEC §6 Phase 2 item 5).

Every save of an agent's configuration creates a new ``agent_versions`` row.
Versions are never mutated, so a run can always be traced to exact settings.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.security import new_id
from app.models.agents import Agent, AgentVersion, Conversation, Message
from app.models.enums import MessageRole
from app.schemas.agents import AgentCreate, AgentUpdate
from app.services import audit

#: Attempts to obtain a free message sequence under concurrent sends.
_MESSAGE_SEQUENCE_ATTEMPTS = 5

#: Applied when a caller supplies no explicit limits.
DEFAULT_LIMITS: dict[str, int] = {"max_steps": 40, "timeout_seconds": 900, "max_tool_calls": 40}

#: Fields that participate in version snapshots.
VERSIONED_FIELDS: tuple[str, ...] = (
    "name",
    "description",
    "role",
    "goal",
    "instructions",
    "runtime",
    "connection_id",
    "model_config_json",
    "tools",
    "limits",
    "permissions",
)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "agent"


async def _unique_slug(session: AsyncSession, organization_id: str, base: str) -> str:
    slug = base
    index = 2
    while await session.scalar(
        select(Agent.id).where(Agent.organization_id == organization_id, Agent.slug == slug)
    ):
        slug = f"{base}-{index}"
        index += 1
    return slug


def _snapshot(
    agent: Agent, payload: AgentCreate | AgentUpdate, version: int, note: str
) -> AgentVersion:
    """Build an immutable snapshot from the post-update agent state."""
    limits = getattr(payload, "limits", None)
    return AgentVersion(
        id=new_id("agv"),
        organization_id=agent.organization_id,
        agent_id=agent.id,
        version=version,
        name=agent.name,
        description=agent.description,
        role=agent.role,
        goal=getattr(payload, "goal", None) or getattr(agent, "goal", "") or "",
        instructions=getattr(payload, "instructions", None) or "",
        runtime=agent.runtime,
        connection_id=agent.connection_id,
        model_config_json=getattr(payload, "model_config_json", None) or {},
        tools=list(getattr(payload, "tools", None) or []),
        limits=(limits.model_dump() if limits is not None else DEFAULT_LIMITS),
        permissions={},
        change_note=note,
    )


async def create_agent(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    payload: AgentCreate,
) -> Agent:
    slug = payload.slug or await _unique_slug(session, organization_id, slugify(payload.name))
    if await session.scalar(
        select(Agent.id).where(Agent.organization_id == organization_id, Agent.slug == slug)
    ):
        raise ConflictError("An agent with this slug already exists", code="slug_taken")

    agent = Agent(
        organization_id=organization_id,
        slug=slug,
        name=payload.name,
        description=payload.description,
        role=payload.role,
        avatar_color=payload.avatar_color,
        runtime=payload.runtime,
        connection_id=payload.connection_id,
        autonomy_level=payload.autonomy_level,
        current_version=1,
    )
    session.add(agent)
    await session.flush()

    session.add(_snapshot(agent, payload, version=1, note="initial version"))
    await audit.record(
        session,
        action="agents.create",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="agent",
        target_id=agent.id,
        context={"slug": slug, "name": agent.name},
    )
    return agent


async def list_agents(
    session: AsyncSession,
    organization_id: str,
    *,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Agent], int]:
    conditions = [Agent.organization_id == organization_id]
    if not include_archived:
        conditions.append(Agent.is_archived.is_(False))
    total = await session.scalar(select(func.count()).select_from(Agent).where(*conditions))
    rows = (
        await session.scalars(
            select(Agent)
            .where(*conditions)
            .order_by(Agent.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(rows), int(total or 0)


async def get_agent(session: AsyncSession, organization_id: str, agent_id: str) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.organization_id != organization_id:
        raise NotFoundError("Agent not found", details={"agent_id": agent_id})
    return agent


async def update_agent(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    agent_id: str,
    payload: AgentUpdate,
) -> Agent:
    """Apply a change and append an immutable version row."""
    agent = await get_agent(session, organization_id, agent_id)
    data = payload.model_dump(exclude_unset=True, exclude={"change_note"})

    for field in ("name", "description", "role", "runtime", "connection_id"):
        if field in data and data[field] is not None:
            setattr(agent, field, data[field])
    if "avatar_color" in data and data["avatar_color"]:
        agent.avatar_color = data["avatar_color"]
    if "autonomy_level" in data:
        agent.autonomy_level = data["autonomy_level"]

    agent.current_version += 1
    await session.flush()

    note = payload.change_note or f"version {agent.current_version}"
    previous = await session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id, AgentVersion.version == agent.current_version - 1
        )
    )
    snapshot = _snapshot(agent, payload, version=agent.current_version, note=note)
    if previous is not None:
        # Unspecified versioned fields inherit from the previous snapshot.
        if payload.goal is None:
            snapshot.goal = previous.goal
        if payload.instructions is None:
            snapshot.instructions = previous.instructions
        if payload.model_config_json is None:
            snapshot.model_config_json = previous.model_config_json
        if payload.tools is None:
            snapshot.tools = list(previous.tools)
        if payload.limits is None:
            snapshot.limits = previous.limits
    session.add(snapshot)
    await audit.record(
        session,
        action="agents.update",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="agent",
        target_id=agent.id,
        context={"version": agent.current_version, "fields": sorted(data)},
    )
    return agent


async def clone_agent(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    agent_id: str,
    new_name: str | None = None,
) -> Agent:
    source = await get_agent(session, organization_id, agent_id)
    latest = await session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == source.id, AgentVersion.version == source.current_version
        )
    )
    if latest is None:
        raise ValidationFailedError("Agent has no version to clone from", code="no_version")
    payload = AgentCreate(
        name=new_name or f"{source.name} (copy)",
        description=latest.description,
        role=latest.role,
        goal=latest.goal,
        instructions=latest.instructions,
        runtime=latest.runtime,  # type: ignore[arg-type]
        connection_id=latest.connection_id,
        model_config_json=latest.model_config_json,
        tools=list(latest.tools),
        avatar_color=source.avatar_color,
    )
    clone = await create_agent(
        session, organization_id=organization_id, actor_id=actor_id, payload=payload
    )
    await audit.record(
        session,
        action="agents.clone",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="agent",
        target_id=clone.id,
        context={"cloned_from": source.id},
    )
    return clone


async def set_enabled(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    agent_id: str,
    enabled: bool,
) -> Agent:
    agent = await get_agent(session, organization_id, agent_id)
    agent.is_enabled = enabled
    await audit.record(
        session,
        action="agents.enable" if enabled else "agents.disable",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="agent",
        target_id=agent.id,
    )
    return agent


async def archive_agent(
    session: AsyncSession, *, organization_id: str, actor_id: str, agent_id: str
) -> Agent:
    agent = await get_agent(session, organization_id, agent_id)
    agent.is_archived = True
    agent.is_enabled = False
    await audit.record(
        session,
        action="agents.archive",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="agent",
        target_id=agent.id,
    )
    return agent


async def list_versions(
    session: AsyncSession, organization_id: str, agent_id: str
) -> list[AgentVersion]:
    await get_agent(session, organization_id, agent_id)
    return list(
        (
            await session.scalars(
                select(AgentVersion)
                .where(AgentVersion.agent_id == agent_id)
                .order_by(AgentVersion.version.desc())
            )
        ).all()
    )


async def get_version(
    session: AsyncSession, organization_id: str, agent_id: str, version: int
) -> AgentVersion:
    await get_agent(session, organization_id, agent_id)
    row = await session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent_id, AgentVersion.version == version
        )
    )
    if row is None:
        raise NotFoundError("Agent version not found", details={"version": version})
    return row


def diff_versions(left: AgentVersion, right: AgentVersion) -> dict[str, dict[str, Any]]:
    """Field-by-field diff between two snapshots (for the UI version history)."""
    changed: dict[str, dict[str, Any]] = {}
    for field in VERSIONED_FIELDS:
        before = getattr(left, field, None)
        after = getattr(right, field, None)
        if before != after:
            changed[field] = {"from": before, "to": after}
    return changed


async def create_conversation(
    session: AsyncSession, *, organization_id: str, agent_id: str, title: str
) -> Conversation:
    await get_agent(session, organization_id, agent_id)
    conversation = Conversation(
        organization_id=organization_id,
        agent_id=agent_id,
        title=title or "New conversation",
    )
    session.add(conversation)
    await session.flush()
    return conversation


async def get_conversation(
    session: AsyncSession, organization_id: str, conversation_id: str
) -> Conversation:
    row = await session.get(Conversation, conversation_id)
    if row is None or row.organization_id != organization_id:
        raise NotFoundError("Conversation not found")
    return row


async def append_message(
    session: AsyncSession,
    *,
    conversation: Conversation,
    role: MessageRole,
    content: str,
    run_id: str | None = None,
    usage: dict | None = None,
    tool_calls: list | None = None,
) -> Message:
    from app.db.base import utcnow

    next_sequence = (
        await session.scalar(
            select(func.coalesce(func.max(Message.sequence), 0)).where(
                Message.conversation_id == conversation.id
            )
        )
        or 0
    ) + 1
    message = Message(
        organization_id=conversation.organization_id,
        conversation_id=conversation.id,
        run_id=run_id,
        role=role,
        content=content,
        usage=usage,
        tool_calls=tool_calls or [],
        sequence=int(next_sequence),
    )
    # ``(conversation_id, sequence)`` is unique. Two concurrent sends can read the
    # same maximum, so the loser retries under a SAVEPOINT and takes the next free
    # number instead of returning an opaque 500.
    for attempt in range(_MESSAGE_SEQUENCE_ATTEMPTS):
        try:
            async with session.begin_nested():
                session.add(message)
                await session.flush()
            break
        except IntegrityError:
            if message in session:  # a savepoint rollback may already detach it
                session.expunge(message)
            if attempt == _MESSAGE_SEQUENCE_ATTEMPTS - 1:
                raise
            message.sequence = (
                await session.scalar(
                    select(func.coalesce(func.max(Message.sequence), 0)).where(
                        Message.conversation_id == conversation.id
                    )
                )
                or 0
            ) + 1
    conversation.last_message_at = utcnow()
    return message


async def list_messages(
    session: AsyncSession, organization_id: str, conversation_id: str, limit: int = 100
) -> list[Message]:
    await get_conversation(session, organization_id, conversation_id)
    return list(
        (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.sequence)
                .limit(limit)
            )
        ).all()
    )
