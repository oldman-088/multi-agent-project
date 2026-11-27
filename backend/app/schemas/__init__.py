"""Pydantic v2 API schemas.

Timestamps are serialized as UTC ISO-8601 with a ``Z`` suffix; event
documents follow the docs/SPEC.md §7 field list exactly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


def _iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


class TZModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


Role = Literal["owner", "admin", "member", "viewer"]


# --- auth -----------------------------------------------------------------


class BootstrapRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=255)
    org_name: str = Field(default="NEXUS", min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=255)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class UserOut(TZModel):
    id: str
    email: str
    role: Role
    organization_id: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class MeResponse(TZModel):
    id: str
    email: str
    role: Role
    organization_id: str


# --- users & organizations --------------------------------------------------


class UserCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=255)
    role: Role = "member"


class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class OrganizationOut(TZModel):
    id: str
    name: str
    created_at: datetime

    @field_serializer("created_at")
    def _ser_created(self, value: datetime) -> str | None:
        return _iso_z(value)


# --- runs -------------------------------------------------------------------


class RunCreateRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=20_000)
    agent_id: str | None = Field(default=None, max_length=64)
    autonomy_level: int | None = Field(default=None, ge=0, le=3)
    allowed_tools: list[str] | None = None
    correlation_id: str | None = Field(default=None, max_length=80)


class RunOut(TZModel):
    id: str
    organization_id: str
    created_by: str
    agent_id: str | None
    goal: str
    status: str
    autonomy_level: int
    allowed_tools: list[str] | None
    correlation_id: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @field_serializer("created_at", "updated_at", "started_at", "finished_at")
    def _ser_dt(self, value: datetime | None) -> str | None:
        return _iso_z(value)


# --- events (docs/SPEC.md §7 document shape) --------------------------------


class EventOut(TZModel):
    event_id: str
    event_version: int
    organization_id: str
    run_id: str | None
    task_id: str | None
    agent_id: str | None
    correlation_id: str | None
    sequence: int
    event_type: str
    timestamp: datetime
    source_runtime: str
    payload: dict[str, Any]

    @field_serializer("timestamp")
    def _ser_ts(self, value: datetime) -> str | None:
        return _iso_z(value)


class EventsResponse(BaseModel):
    events: list[EventOut]


# --- tool gateway ------------------------------------------------------------


class ToolCallRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallOut(TZModel):
    id: str
    organization_id: str
    run_id: str
    tool: str
    arguments: dict[str, Any]
    policy_decision: str
    policy_reason: str
    status: str
    result: dict[str, Any] | None
    error: str | None
    requested_by: str
    decided_by: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: float | None

    @field_serializer("created_at", "started_at", "completed_at")
    def _ser_dt(self, value: datetime | None) -> str | None:
        return _iso_z(value)


class ApprovalOut(TZModel):
    id: str
    organization_id: str
    run_id: str
    tool_call_id: str
    status: str
    requested_by: str
    decided_by: str | None
    created_at: datetime
    decided_at: datetime | None

    @field_serializer("created_at", "decided_at")
    def _ser_dt(self, value: datetime | None) -> str | None:
        return _iso_z(value)


class ToolSpecOut(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    requires_approval: bool


class ToolsResponse(BaseModel):
    tools: list[ToolSpecOut]


# --- emergency stop -----------------------------------------------------------


class EmergencyStopRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2_000)


class EmergencyStopStateOut(BaseModel):
    engaged: bool
    reason: str | None
    engaged_by: str | None
    engaged_at: datetime | None
    cleared_by: str | None
    cleared_at: datetime | None

    @field_serializer("engaged_at", "cleared_at")
    def _ser_dt(self, value: datetime | None) -> str | None:
        return _iso_z(value)


class EmergencyStopResultOut(BaseModel):
    engaged: bool
    engaged_at: datetime
    cancelled_runs: int

    @field_serializer("engaged_at")
    def _ser_dt(self, value: datetime) -> str | None:
        return _iso_z(value)


class EmergencyStopClearedOut(BaseModel):
    engaged: bool
    cleared_at: datetime

    @field_serializer("cleared_at")
    def _ser_dt(self, value: datetime) -> str | None:
        return _iso_z(value)


# --- health --------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    database: str


__all__ = [
    "ApprovalOut",
    "BootstrapRequest",
    "EmergencyStopClearedOut",
    "EmergencyStopRequest",
    "EmergencyStopResultOut",
    "EmergencyStopStateOut",
    "EventOut",
    "EventsResponse",
    "HealthResponse",
    "LoginRequest",
    "MeResponse",
    "OrganizationCreateRequest",
    "OrganizationOut",
    "RefreshRequest",
    "RunCreateRequest",
    "RunOut",
    "TokenResponse",
    "ToolCallOut",
    "ToolCallRequest",
    "ToolSpecOut",
    "ToolsResponse",
    "UserCreateRequest",
    "UserOut",
]
