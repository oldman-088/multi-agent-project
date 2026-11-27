"""Run, event, approval, audit and tool schemas (SPEC §7)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.models.enums import (
    ApprovalKind,
    ApprovalStatus,
    AuditOutcome,
    RunStatus,
    RunTrigger,
)
from backend.app.schemas.common import ORMModel

#: The complete event-type vocabulary of SPEC §7. Emitting anything else is a bug.
EVENT_TYPES: frozenset[str] = frozenset(
    {
        "run.created",
        "run.started",
        "run.paused",
        "run.resumed",
        "run.completed",
        "run.failed",
        "run.cancelled",
        "agent.started",
        "agent.message",
        "agent.stream",
        "agent.code",
        "agent.delegated",
        "agent.waiting",
        "agent.completed",
        "agent.failed",
        "plan.proposed",
        "plan.approved",
        "plan.rejected",
        "task.created",
        "task.assigned",
        "task.started",
        "task.completed",
        "task.failed",
        "tool.execution.started",
        "tool.execution.completed",
        "tool.execution.failed",
        "approval.requested",
        "approval.approved",
        "approval.rejected",
        "pr.opened",
        "pr.reviewed",
        "pr.merged",
        "pr.closed",
        "checkpoint.created",
        "artifact.created",
        "memory.updated",
        "connection.state_changed",
        "browser.connected",
        "browser.disconnected",
        "browser.session.expired",
        "browser.waiting_for_user",
        "browser.resumed",
        "provider.response.received",
        "system.health",
        "emergency_stop.engaged",
        "emergency_stop.cleared",
    }
)


class RunCreate(BaseModel):
    agent_id: str
    directive: str = Field(default="", max_length=120_000)
    conversation_id: str | None = None
    trigger: RunTrigger = RunTrigger.MANUAL
    idempotency_key: str | None = Field(
        default=None,
        max_length=120,
        description="Two requests with the same key return the same run (no duplicate work).",
    )


class RunOut(ORMModel):
    id: str
    agent_id: str
    agent_version_id: str | None = None
    conversation_id: str | None = None
    connection_id: str | None = None
    status: RunStatus
    trigger: RunTrigger
    directive: str
    last_sequence: int
    step_count: int
    tool_call_count: int
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class RunDetail(RunOut):
    latest_checkpoint_step: int | None = None
    pending_approvals: int = 0


class RunListFilter(BaseModel):
    status: RunStatus | None = None
    agent_id: str | None = None


class EventOut(ORMModel):
    event_id: str = Field(validation_alias="id", serialization_alias="event_id")
    event_version: int
    organization_id: str
    run_id: str | None = None
    task_id: str | None = None
    agent_id: str | None = None
    correlation_id: str | None = None
    sequence: int
    event_type: str
    timestamp: datetime = Field(validation_alias="created_at", serialization_alias="timestamp")
    source_runtime: str
    payload: dict

    model_config = ORMModel.model_config | {"populate_by_name": True}


class EventCreate(BaseModel):
    """Internal/API event append. ``event_type`` must be in EVENT_TYPES."""

    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None
    task_id: str | None = None
    agent_id: str | None = None
    correlation_id: str | None = None
    sequence: int | None = Field(
        default=None, description="Server assigns the next per-run sequence when omitted."
    )
    source_runtime: str = "native"


class CheckpointOut(ORMModel):
    id: str
    run_id: str
    step: int
    label: str
    state: dict
    resumable: bool
    created_at: datetime


class ToolOut(ORMModel):
    id: str
    slug: str
    display_name: str
    description: str
    input_schema: dict
    requires_approval: bool
    enabled: bool
    category: str


class ToolInvokeRequest(BaseModel):
    tool_slug: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None
    agent_id: str | None = None


class ToolInvokeResult(BaseModel):
    """Result of a Tool Gateway call. Every call is audited."""

    invocation_id: str
    tool_slug: str
    decision: str
    outcome: str
    result: dict[str, Any] | None = None
    error: str | None = None
    approval_id: str | None = None
    duration_ms: int


class ApprovalOut(ORMModel):
    id: str
    kind: ApprovalKind
    status: ApprovalStatus
    run_id: str | None = None
    agent_id: str | None = None
    tool_slug: str | None = None
    requested_payload: dict
    reason: str
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    created_at: datetime


class ApprovalDecision(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=600)


class AuditLogOut(ORMModel):
    id: str
    actor_id: str | None = None
    actor_type: str
    action: str
    target_type: str | None = None
    target_id: str | None = None
    outcome: AuditOutcome
    context: dict
    ip_address: str | None = None
    request_id: str | None = None
    created_at: datetime


class TimelineStep(BaseModel):
    """One of the 8 workflow steps, computed from real rows (SPEC §1)."""

    step: int
    key: Literal[
        "request",
        "analyze",
        "distribute",
        "execute",
        "collect",
        "pull_request",
        "review_merge",
        "completed",
    ]
    state: Literal["pending", "active", "done", "failed", "waiting_for_user"]
    label: str
    detail: str | None = None


class MissionTimeline(BaseModel):
    mission_id: str
    steps: list[TimelineStep]
    tasks_total: int
    tasks_done: int
    pull_requests: int
    elapsed_seconds: int | None = None


class EmergencyStopRequest(BaseModel):
    engage: bool
    reason: str = Field(default="", max_length=400)


class EmergencyStopState(BaseModel):
    engaged: bool
    reason: str | None = None
