"""Agents with immutable versioning (SPEC §6 Phase 2 item 5)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PublicIdMixin, TimestampMixin, UTCDateTime
from app.db.types import EnumValue, JSONType
from app.models.enums import AutonomyLevel


class Agent(Base, PublicIdMixin, TimestampMixin):
    """A configured AI employee. Runs reference an immutable ``agent_version``."""

    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_agents_org_slug"),
        Index("ix_agents_org", "organization_id"),
    )
    id_prefix = "agt"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(600), default="", nullable=False)
    role: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    avatar_color: Mapped[str] = mapped_column(String(9), default="#6366f1", nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    #: Current head version. A run always references the exact version it used.
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    runtime: Mapped[str] = mapped_column(String(32), default="native", nullable=False)
    connection_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("provider_connections.id", ondelete="SET NULL"), nullable=True
    )
    autonomy_level: Mapped[AutonomyLevel | None] = mapped_column(
        EnumValue(AutonomyLevel), nullable=True
    )


class AgentVersion(Base, TimestampMixin):
    """Immutable snapshot of an agent's configuration. Never updated in place."""

    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),
        Index("ix_agent_versions_agent", "agent_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(600), default="", nullable=False)
    role: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    goal: Mapped[str] = mapped_column(Text, default="", nullable=False)
    instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    runtime: Mapped[str] = mapped_column(String(32), default="native", nullable=False)
    connection_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_config_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    #: Tool allow-list. An agent may only call tools listed here (SPEC Phase 2.7).
    tools: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    limits: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    permissions: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    change_note: Mapped[str] = mapped_column(String(400), default="", nullable=False)


class Conversation(Base, PublicIdMixin, TimestampMixin):
    """A chat thread between the owner and an agent."""

    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_org", "organization_id"),
        Index("ix_conversations_agent", "agent_id"),
    )
    id_prefix = "cnv"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    is_archived: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    last_message_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Message(Base, PublicIdMixin, TimestampMixin):
    """A single chat message. ``usage`` stays null unless the connection reports it."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation", "conversation_id", "created_at"),)
    id_prefix = "msg"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tool_calls: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    attachments: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    #: Honest usage: null when the connection does not report it (SPEC §3.3).
    usage: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
