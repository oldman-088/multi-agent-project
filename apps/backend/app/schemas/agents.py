"""Agent, agent-version, conversation and message schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel


class AgentLimits(BaseModel):
    """Hard caps. ``0`` means unlimited (SPEC §13.2 budgets)."""

    max_steps: int = Field(default=40, ge=0, le=1000)
    timeout_seconds: int = Field(default=900, ge=0, le=86_400)
    max_tool_calls: int = Field(default=40, ge=0, le=1000)


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120, examples=["Backend Engineer"])
    slug: str | None = Field(default=None, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str = Field(default="", max_length=600)
    role: str = Field(default="", max_length=120)
    goal: str = Field(default="", max_length=8000)
    instructions: str = Field(default="", max_length=40_000)
    runtime: Literal["native", "software_team"] = "native"
    connection_id: str | None = None
    model_config_json: dict = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)
    limits: AgentLimits = Field(default_factory=AgentLimits)
    #: Autonomy override for this agent (SPEC §13.1).
    autonomy_level: Literal["0", "1", "2", "3"] | None = None
    avatar_color: str = Field(default="#6366f1", pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("tools")
    @classmethod
    def _no_duplicate_tools(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("tools must not contain duplicates")
        return value


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=600)
    role: str | None = Field(default=None, max_length=120)
    goal: str | None = Field(default=None, max_length=8000)
    instructions: str | None = Field(default=None, max_length=40_000)
    runtime: Literal["native", "software_team"] | None = None
    connection_id: str | None = None
    model_config_json: dict | None = None
    tools: list[str] | None = None
    limits: AgentLimits | None = None
    autonomy_level: Literal["0", "1", "2", "3"] | None = None
    avatar_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    change_note: str = Field(default="", max_length=400)


class AgentVersionOut(ORMModel):
    id: str
    agent_id: str
    version: int
    name: str
    description: str
    role: str
    goal: str
    instructions: str
    runtime: str
    connection_id: str | None = None
    model_config_json: dict
    tools: list
    limits: dict
    permissions: dict
    change_note: str
    created_at: datetime


class AgentOut(ORMModel):
    id: str
    slug: str
    name: str
    description: str
    role: str
    avatar_color: str
    is_enabled: bool
    is_archived: bool
    current_version: int
    runtime: str
    connection_id: str | None = None
    autonomy_level: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentDetail(AgentOut):
    """Agent plus the exact configuration snapshot its runs reference."""

    current_version_detail: AgentVersionOut | None = None


class AgentVersionDiff(BaseModel):
    from_version: int
    to_version: int
    changed_fields: dict[str, dict[str, object]]


class ConversationCreate(BaseModel):
    agent_id: str
    title: str = Field(default="", max_length=200)


class ConversationOut(ORMModel):
    id: str
    agent_id: str
    title: str
    is_archived: bool
    last_message_at: datetime | None = None
    created_at: datetime


class MessageOut(ORMModel):
    id: str
    conversation_id: str
    run_id: str | None = None
    role: str
    content: str
    tool_calls: list
    attachments: list
    usage: dict | None = None
    sequence: int
    created_at: datetime


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=120_000)
    attachments: list[dict] = Field(default_factory=list)
