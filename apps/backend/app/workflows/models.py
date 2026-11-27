"""SQLAlchemy models for durable workflow task state (atomic claims).

The ``workflow_tasks`` table backs :mod:`app.workflows.claims`.  It is created
by the Alembic revision in ``apps/backend/migrations`` and is the only table the
orchestration slice owns; platform tables (users, organizations, …) belong to
the backend slice and its own migration chain.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .status import TaskStatus


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp (SQLite stores it without the tz marker)."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for workflow-engine tables."""


class WorkflowTaskRecord(Base):
    """One task of one workflow run, with its claim and attempt state."""

    __tablename__ = "workflow_tasks"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(sa.String(64), index=True)
    task_key: Mapped[str] = mapped_column(sa.String(128))
    status: Mapped[str] = mapped_column(sa.String(32), default=TaskStatus.PENDING.value, index=True)
    attempts: Mapped[int] = mapped_column(sa.Integer, default=0, server_default=sa.text("0"))
    max_attempts: Mapped[int] = mapped_column(sa.Integer, default=1, server_default=sa.text("1"))
    claim_token: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    result_json: Mapped[Any | None] = mapped_column(sa.JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("workflow_id", "task_key", name="uq_workflow_tasks_workflow_key"),
        sa.Index("ix_workflow_tasks_status_key", "status", "task_key"),
    )
