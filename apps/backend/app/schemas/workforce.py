"""Mission, task, pull request and review schemas (SPEC §6 Phase 3)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class TaskSpec(BaseModel):
    """One node of the task DAG supplied by the manager plan."""

    key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20_000)
    specialty: str = Field(default="general", max_length=48)
    depends_on: list[str] = Field(default_factory=list, max_length=50)
    max_attempts: int = Field(default=3, ge=1, le=10)
    contract: str | None = Field(
        default=None,
        max_length=200,
        description="Shared contract path (e.g. docs/API.md) when this task touches both sides.",
    )


class MissionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    directive: str = Field(default="", max_length=120_000)
    team_id: str | None = None
    tasks: list[TaskSpec] = Field(default_factory=list, max_length=200)
    assumptions: list[str] = Field(default_factory=list, max_length=50)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=50)


class MissionOut(ORMModel):
    id: str
    title: str
    directive: str
    status: str
    team_id: str | None = None
    assumptions: list
    acceptance_criteria: list
    plan: dict
    plan_validation: dict
    replan_budget: int
    replans_used: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class TaskOut(ORMModel):
    id: str
    mission_id: str
    title: str
    description: str
    specialty: str
    status: str
    assignee_agent_id: str | None = None
    run_id: str | None = None
    claimed_by: str | None = None
    attempt: int
    max_attempts: int
    branch_name: str | None = None
    is_parked: bool
    error: str | None = None


class PullRequestCreate(BaseModel):
    mission_id: str | None = None
    task_id: str | None = None
    repository: str = Field(
        min_length=1, max_length=200, examples=["oldman-088/multi-agent-project"]
    )
    number: int | None = Field(default=None, ge=1)
    url: str | None = Field(default=None, max_length=600)
    title: str = Field(default="", max_length=300)
    branch: str = Field(min_length=1, max_length=200)
    base_branch: str = Field(default="main", max_length=120)
    is_draft: bool = True


class PullRequestOut(ORMModel):
    id: str
    mission_id: str | None = None
    task_id: str | None = None
    repository: str
    number: int | None = None
    url: str | None = None
    title: str
    branch: str
    base_branch: str
    is_draft: bool
    status: str
    checks_status: str
    merged_at: datetime | None = None
    created_at: datetime


class ReviewCreate(BaseModel):
    verdict: Literal["approve", "request_changes", "comment", "reject"]
    summary: str = Field(default="", max_length=20_000)
    reviewer_agent_id: str | None = None
    parse_attempts: int = Field(default=1, ge=1, le=5)


class ReviewOut(ORMModel):
    id: str
    pull_request_id: str
    reviewer_agent_id: str | None = None
    verdict: str
    summary: str
    parse_attempts: int
    human_approved_by: str | None = None
    created_at: datetime
