"""Runs, events (the authoritative execution history), checkpoints."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base, PublicIdMixin, TimestampMixin, UTCDateTime
from backend.app.db.types import EnumValue, JSONType
from backend.app.models.enums import RunStatus, RunTrigger


class Run(Base, PublicIdMixin, TimestampMixin):
    """A single agent run. State lives here plus checkpoints — nothing hidden."""

    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_org", "organization_id"),
        Index("ix_runs_agent", "agent_id"),
        Index("ix_runs_status", "status"),
        # Idempotent run creation per client-supplied key (SPEC §6 P1 item 3).
        UniqueConstraint("organization_id", "idempotency_key", name="uq_runs_org_idempotency"),
    )
    id_prefix = "run"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    agent_version_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    connection_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("provider_connections.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[RunStatus] = mapped_column(
        EnumValue(RunStatus), default=RunStatus.CREATED, nullable=False
    )
    trigger: Mapped[RunTrigger] = mapped_column(
        EnumValue(RunTrigger), default=RunTrigger.MANUAL, nullable=False
    )
    directive: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Monotonic per-run event counter; the event table is the source of truth.
    last_sequence: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    step_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    tool_call_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error: Mapped[str | None] = mapped_column(String(600), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Event(Base, TimestampMixin):
    """Authoritative execution history (SPEC §4.3, §7).

    Written in the same transaction as the state change (outbox pattern) and
    then published to clients, which replay from ``sequence`` on reconnect.
    """

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_events_run_sequence"),
        Index("ix_events_org_created", "organization_id", "created_at"),
        Index("ix_events_run_seq", "run_id", "sequence"),
        Index("ix_events_type", "event_type"),
    )

    #: Globally sortable id; also the resume cursor for WebSocket clients.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="CASCADE"), nullable=True
    )
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_runtime: Mapped[str] = mapped_column(String(32), default="native", nullable=False)
    #: Payloads are secret-redacted before insertion (SPEC §7 rules).
    payload: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)


class Checkpoint(Base, TimestampMixin):
    """Run checkpoint so a restarted worker can resume (SPEC §4.3, §13.3)."""

    __tablename__ = "checkpoints"
    __table_args__ = (
        UniqueConstraint("run_id", "step", name="uq_checkpoints_run_step"),
        Index("ix_checkpoints_run", "run_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    state: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    resumable: Mapped[bool] = mapped_column(default=True, nullable=False, server_default="1")


class ToolDefinition(Base, TimestampMixin):
    """The Tool Registry (SPEC §6 Phase 2 item 7)."""

    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_tools_org_slug"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(600), default="", nullable=False)
    #: JSON Schema for arguments; every call is validated against it.
    input_schema: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(
        default=False, server_default=false(), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(default=True, server_default="1", nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="builtin", nullable=False)


class ToolInvocation(Base, PublicIdMixin, TimestampMixin):
    """Every tool call is audited, allowed, asked about or denied (SPEC §3.2)."""

    __tablename__ = "tool_invocations"
    __table_args__ = (
        Index("ix_tool_invocations_org", "organization_id"),
        Index("ix_tool_invocations_run", "run_id"),
    )
    id_prefix = "tcl"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_slug: Mapped[str] = mapped_column(String(80), nullable=False)
    arguments: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), default="allow", nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), default="success", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Approval(Base, PublicIdMixin, TimestampMixin):
    """Pending decisions a human must make (SPEC §8.3-H Approvals inbox)."""

    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_org_status", "organization_id", "status"),
        Index("ix_approvals_run", "run_id"),
    )
    id_prefix = "apr"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), default="tool_call", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="CASCADE"), nullable=True
    )
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_slug: Mapped[str | None] = mapped_column(String(80), nullable=True)
    requested_payload: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    reason: Mapped[str] = mapped_column(String(600), default="", nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(600), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class AuditLog(Base, TimestampMixin):
    """Append-only audit trail. Never updated except to redact a leaked secret."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_org_created", "organization_id", "created_at"),
        Index("ix_audit_logs_actor", "actor_id"),
        Index("ix_audit_logs_action", "action"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), default="success", nullable=False)
    #: Request context. Secret-redacted, never contains prompt content.
    context: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Schedule(Base, PublicIdMixin, TimestampMixin):
    """One-time / interval / cron schedules for missions (SPEC §6 Phase 6)."""

    __tablename__ = "schedules"
    __table_args__ = (Index("ix_schedules_org", "organization_id"),)
    id_prefix = "sch"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="once", nullable=False)
    expression: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    directive: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, server_default="1", nullable=False)
    max_runs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    run_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
