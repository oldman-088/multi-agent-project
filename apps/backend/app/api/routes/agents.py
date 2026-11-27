"""Agent CRUD, immutable versions, cloning and conversations."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select

from app.auth.dependencies import CurrentAuth, CurrentSession, require
from app.models.agents import AgentVersion, Conversation
from app.models.enums import MessageRole
from app.schemas.agents import (
    AgentCreate,
    AgentDetail,
    AgentOut,
    AgentUpdate,
    AgentVersionDiff,
    AgentVersionOut,
    ConversationCreate,
    ConversationOut,
    MessageCreate,
    MessageOut,
)
from app.schemas.common import OkResponse, Page
from app.services import agent_service

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=Page[AgentOut], summary="List agents")
async def list_agents(
    auth: CurrentAuth,
    session: CurrentSession,
    include_archived: bool = Query(default=False),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AgentOut]:
    auth.require("agents:read")
    rows, total = await agent_service.list_agents(
        session,
        auth.organization_id,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )
    return Page(
        items=[AgentOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=AgentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an agent (creates version 1)",
    dependencies=[Depends(require("agents:write"))],
)
async def create_agent(
    payload: AgentCreate, auth: CurrentAuth, session: CurrentSession
) -> AgentOut:
    agent = await agent_service.create_agent(
        session, organization_id=auth.organization_id, actor_id=auth.user.id, payload=payload
    )
    await session.commit()
    return AgentOut.model_validate(agent)


@router.get(
    "/{agent_id}", response_model=AgentDetail, summary="Get an agent with its current version"
)
async def get_agent(agent_id: str, auth: CurrentAuth, session: CurrentSession) -> AgentDetail:
    auth.require("agents:read")
    agent = await agent_service.get_agent(session, auth.organization_id, agent_id)
    version = await session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id, AgentVersion.version == agent.current_version
        )
    )
    detail = AgentDetail.model_validate(agent)
    detail.current_version_detail = (
        AgentVersionOut.model_validate(version) if version is not None else None
    )
    return detail


@router.patch(
    "/{agent_id}", response_model=AgentOut, summary="Update an agent (new immutable version)"
)
async def update_agent(
    agent_id: str, payload: AgentUpdate, auth: CurrentAuth, session: CurrentSession
) -> AgentOut:
    auth.require("agents:write")
    agent = await agent_service.update_agent(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        agent_id=agent_id,
        payload=payload,
    )
    await session.commit()
    return AgentOut.model_validate(agent)


@router.post(
    "/{agent_id}/clone",
    response_model=AgentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Clone an agent",
)
async def clone_agent(
    agent_id: str,
    auth: CurrentAuth,
    session: CurrentSession,
    name: str | None = Query(default=None, max_length=120),
) -> AgentOut:
    auth.require("agents:write")
    clone = await agent_service.clone_agent(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        agent_id=agent_id,
        new_name=name,
    )
    await session.commit()
    return AgentOut.model_validate(clone)


@router.post("/{agent_id}/enable", response_model=AgentOut, summary="Enable or disable an agent")
async def set_enabled(
    agent_id: str,
    enabled: Annotated[bool, Query()],
    auth: CurrentAuth,
    session: CurrentSession,
) -> AgentOut:
    auth.require("agents:write")
    agent = await agent_service.set_enabled(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        agent_id=agent_id,
        enabled=enabled,
    )
    await session.commit()
    return AgentOut.model_validate(agent)


@router.delete("/{agent_id}", response_model=OkResponse, summary="Archive an agent (soft delete)")
async def archive_agent(agent_id: str, auth: CurrentAuth, session: CurrentSession) -> OkResponse:
    auth.require("agents:write")
    await agent_service.archive_agent(
        session, organization_id=auth.organization_id, actor_id=auth.user.id, agent_id=agent_id
    )
    await session.commit()
    return OkResponse(message="Agent archived")


@router.get(
    "/{agent_id}/versions",
    response_model=list[AgentVersionOut],
    summary="Version history (newest first)",
)
async def list_versions(
    agent_id: str, auth: CurrentAuth, session: CurrentSession
) -> list[AgentVersionOut]:
    auth.require("agents:read")
    rows = await agent_service.list_versions(session, auth.organization_id, agent_id)
    return [AgentVersionOut.model_validate(row) for row in rows]


@router.get(
    "/{agent_id}/versions/{version}",
    response_model=AgentVersionOut,
    summary="One version snapshot",
)
async def get_version(
    agent_id: str, version: int, auth: CurrentAuth, session: CurrentSession
) -> AgentVersionOut:
    auth.require("agents:read")
    row = await agent_service.get_version(session, auth.organization_id, agent_id, version)
    return AgentVersionOut.model_validate(row)


@router.get(
    "/{agent_id}/versions/{from_version}/diff/{to_version}",
    response_model=AgentVersionDiff,
    summary="Field diff between two versions",
)
async def diff_versions(
    agent_id: str, from_version: int, to_version: int, auth: CurrentAuth, session: CurrentSession
) -> AgentVersionDiff:
    auth.require("agents:read")
    left = await agent_service.get_version(session, auth.organization_id, agent_id, from_version)
    right = await agent_service.get_version(session, auth.organization_id, agent_id, to_version)
    return AgentVersionDiff(
        from_version=from_version,
        to_version=to_version,
        changed_fields=agent_service.diff_versions(left, right),
    )


@router.get("/{agent_id}/tools", response_model=list[str], summary="The agent's tool allow-list")
async def agent_tools(agent_id: str, auth: CurrentAuth, session: CurrentSession) -> list[str]:
    auth.require("agents:read")
    agent = await agent_service.get_agent(session, auth.organization_id, agent_id)
    version = await session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id, AgentVersion.version == agent.current_version
        )
    )
    return list(version.tools if version else [])


conversations_router = APIRouter(prefix="/conversations", tags=["conversations"])


@conversations_router.post(
    "",
    response_model=ConversationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Start a conversation with an agent",
    dependencies=[Depends(require("conversations:write"))],
)
async def create_conversation(
    payload: ConversationCreate, auth: CurrentAuth, session: CurrentSession
) -> ConversationOut:
    conversation = await agent_service.create_conversation(
        session,
        organization_id=auth.organization_id,
        agent_id=payload.agent_id,
        title=payload.title,
    )
    await session.commit()
    return ConversationOut.model_validate(conversation)


@conversations_router.get("", response_model=Page[ConversationOut], summary="List conversations")
async def list_conversations(
    auth: CurrentAuth,
    session: CurrentSession,
    agent_id: str | None = Query(default=None),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ConversationOut]:
    auth.require("conversations:read")
    conditions = [Conversation.organization_id == auth.organization_id]
    if agent_id:
        conditions.append(Conversation.agent_id == agent_id)
    from sqlalchemy import func

    total = await session.scalar(select(func.count()).select_from(Conversation).where(*conditions))
    rows = (
        await session.scalars(
            select(Conversation)
            .where(*conditions)
            .order_by(Conversation.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return Page(
        items=[ConversationOut.model_validate(row) for row in rows],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


@conversations_router.get(
    "/{conversation_id}/messages", response_model=list[MessageOut], summary="Message history"
)
async def list_messages(
    conversation_id: str,
    auth: CurrentAuth,
    session: CurrentSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[MessageOut]:
    auth.require("conversations:read")
    rows = await agent_service.list_messages(session, auth.organization_id, conversation_id, limit)
    return [MessageOut.model_validate(row) for row in rows]


@conversations_router.post(
    "/{conversation_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
    summary="Append a user message",
)
async def append_message(
    conversation_id: str, payload: MessageCreate, auth: CurrentAuth, session: CurrentSession
) -> MessageOut:
    auth.require("conversations:write")
    conversation = await agent_service.get_conversation(
        session, auth.organization_id, conversation_id
    )
    message = await agent_service.append_message(
        session,
        conversation=conversation,
        role=MessageRole.USER,
        content=payload.content,
    )
    await session.commit()
    return MessageOut.model_validate(message)
