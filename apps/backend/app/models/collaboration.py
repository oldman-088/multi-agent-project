"""Teams, missions, tasks, dependencies, PRs and reviews (SPEC §6 Phase 3)."""

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
from app.models.enums import MessageRole


class Team(Base, PublicIdMixin, TimestampMixin):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_teams_org_slug"),
        Index("ix_teams_org", "organization_id"),
    )
    id_prefix = "tm"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    pattern: Mapped[str] = mapped_column(String(24), default="sequential", nullable=False)
    description: Mapped[str] = mapped_column(String(600), default="", nullable=False)
    manager_agent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )


class TeamMember(Base, TimestampMixin):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "agent_id", name="uq_team_members_pair"),)

    team_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    member_role: Mapped[str] = mapped_column(String(32), default="worker", nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Mission(Base, PublicIdMixin, TimestampMixin):
    """A directive decomposed into a task DAG (SPEC §6 Phase 3, §14)."""

    __tablename__ = "missions"
    __table_args__ = (Index("ix_missions_org", "organization_id"),)
    id_prefix = "msn"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    directive: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Stated assumptions when a directive is ambiguous (SPEC §14.4).
    assumptions: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    acceptance_criteria: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    plan: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    #: DAG validation result: no cycles, contract warnings (SPEC §6 Phase 3).
    plan_validation: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    replan_budget: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    replans_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    parent_mission_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("missions.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Task(Base, PublicIdMixin, TimestampMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_mission", "mission_id"),
        Index("ix_tasks_status", "status"),
    )
    id_prefix = "tsk"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    mission_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("missions.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    specialty: Mapped[str] = mapped_column(String(48), default="general", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    assignee_agent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    #: Atomic claim: only one worker may transition a task to running.
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    branch_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    worktree_path: Mapped[str | None] = mapped_column(String(600), nullable=True)
    is_parked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    error: Mapped[str | None] = mapped_column(String(600), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class TaskDependency(Base, TimestampMixin):
    __tablename__ = "task_dependencies"

    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )


class PullRequest(Base, PublicIdMixin, TimestampMixin):
    __tablename__ = "pull_requests"
    __table_args__ = (Index("ix_pull_requests_mission", "mission_id"),)
    id_prefix = "pr"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    mission_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("missions.id", ondelete="SET NULL"), nullable=True
    )
    task_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    repository: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    title: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    branch: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    base_branch: Mapped[str] = mapped_column(String(120), default="main", nullable=False)
    is_draft: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), default="open", nullable=False)
    checks_status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    merged_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Review(Base, PublicIdMixin, TimestampMixin):
    """An AI reviewer verdict. AI reviewers can never approve a merge (§3.1/§13)."""

    __tablename__ = "reviews"
    __table_args__ = (Index("ix_reviews_pull_request", "pull_request_id"),)
    id_prefix = "rev"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    pull_request_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("pull_requests.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verdict: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    comments: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    parse_attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    human_approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    human_approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class BusMessage(Base, PublicIdMixin, TimestampMixin):
    """Persisted inter-agent message bus (SPEC §6 Phase 3)."""

    __tablename__ = "bus_messages"
    __table_args__ = (
        Index("ix_bus_messages_org", "organization_id"),
        Index("ix_bus_messages_correlation", "correlation_id"),
    )
    id_prefix = "bmsg"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(120), default="broadcast", nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="broadcast", nullable=False)
    sender_type: Mapped[str] = mapped_column(String(16), default="agent", nullable=False)
    sender_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recipient_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mission_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Reuse of MessageRole keeps sender semantics consistent across the bus.
    role: Mapped[MessageRole] = mapped_column(
        EnumValue(MessageRole), default=MessageRole.ASSISTANT, nullable=False
    )
