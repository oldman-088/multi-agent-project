"""SQLAlchemy models — the single source of truth for execution state.

docs/SPEC.md §4.3: the ``events`` table is the authoritative execution
history; every state change writes its event in the same transaction (outbox
pattern). All tenant-scoped tables carry ``organization_id`` (§2 Phase 2).
Timestamps are stored as naive UTC and serialized as UTC ISO-8601 with a
``Z`` suffix.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.app.core.redaction import redact_value


def utcnow() -> datetime:
    """Naive UTC now (SQLite stores naive; serializers re-attach UTC)."""
    return datetime.now(UTC).replace(tzinfo=None)


def _prefixed_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _prefixed_id("org")
    )
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class User(Base):
    """A member of one organization with a role (§2 Phase 2 RBAC)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _prefixed_id("usr")
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))  # owner | admin | member | viewer
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _prefixed_id("run")
    )
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    goal: Mapped[str] = mapped_column(Text)
    # pending | running | completed | cancelled | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    autonomy_level: Mapped[int] = mapped_column(Integer, default=3)
    # Tool allow-list; None means "every registered tool" (§2 Phase 2 item 7).
    allowed_tools: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), default=lambda: uuid.uuid4().hex)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Event(Base):
    """One normalized execution event (docs/SPEC.md §7).

    ``sequence`` is monotonic per run (unique constraint as a race backstop);
    global events (``run_id IS NULL``, e.g. ``emergency_stop.engaged``) draw
    their sequence from the same per-run-style MAX+1 query over the global
    namespace.
    """

    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_events_run_sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(80), unique=True, index=True, default=lambda: _prefixed_id("evt")
    )
    event_version: Mapped[int] = mapped_column(Integer, default=1)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source_runtime: Mapped[str] = mapped_column(String(32), default="native")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ToolCall(Base):
    """Audit row for every Tool Gateway decision (docs/SPEC.md §3.2).

    The gateway ALWAYS audits: allowed, asked-about and denied calls all get a
    row here. ``arguments`` and ``result`` are stored redacted.
    """

    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _prefixed_id("tc")
    )
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    tool: Mapped[str] = mapped_column(String(64), index=True)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # allow | ask | deny
    policy_decision: Mapped[str] = mapped_column(String(8))
    policy_reason: Mapped[str] = mapped_column(String(64))
    # pending_approval | executing | completed | failed | denied | rejected
    status: Mapped[str] = mapped_column(String(24), index=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(nullable=True)


class Approval(Base):
    """A human decision on a gateway ``ask`` decision (§2 approvals table)."""

    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _prefixed_id("appr")
    )
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    tool_call_id: Mapped[str] = mapped_column(ForeignKey("tool_calls.id"), unique=True)
    # pending | approved | rejected
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EmergencyStop(Base):
    """Global kill-switch state (docs/SPEC.md §3.2).

    A single row (id=1). The switch is global and cannot be disabled by any
    autonomy level; engaging it cancels every active run.
    """

    __tablename__ = "emergency_stop"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    engaged: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    engaged_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    engaged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cleared_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


def redacted(value: dict[str, Any] | None) -> dict[str, Any]:
    """Redact a payload before persisting it (defense in depth for §7)."""
    if value is None:
        return {}
    redacted_value = redact_value(value)
    assert isinstance(redacted_value, dict)
    return redacted_value


__all__ = [
    "Approval",
    "Base",
    "EmergencyStop",
    "Event",
    "Organization",
    "Run",
    "ToolCall",
    "User",
    "redacted",
    "utcnow",
]
