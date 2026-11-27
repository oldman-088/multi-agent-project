"""Missions, task DAG, timeline, pull requests and reviews (SPEC §1, §6 Phase 3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.auth.dependencies import CurrentAuth, CurrentSession, require
from app.schemas.common import Page
from app.schemas.runs import MissionTimeline
from app.schemas.workforce import (
    MissionCreate,
    MissionOut,
    PullRequestCreate,
    PullRequestOut,
    ReviewCreate,
    ReviewOut,
    TaskOut,
)
from app.services import mission_service

router = APIRouter(prefix="/missions", tags=["missions"])
pr_router = APIRouter(prefix="/pull-requests", tags=["pull-requests"])


@router.get("", response_model=Page[MissionOut], summary="List missions")
async def list_missions(
    auth: CurrentAuth,
    session: CurrentSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[MissionOut]:
    auth.require("missions:read")
    rows, total = await mission_service.list_missions(
        session, auth.organization_id, limit=limit, offset=offset
    )
    return Page(
        items=[MissionOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=MissionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a mission with a validated task DAG",
    dependencies=[Depends(require("missions:write"))],
)
async def create_mission(
    payload: MissionCreate, auth: CurrentAuth, session: CurrentSession
) -> MissionOut:
    mission = await mission_service.create_mission(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        title=payload.title,
        directive=payload.directive,
        team_id=payload.team_id,
        tasks=[task.model_dump() for task in payload.tasks] if payload.tasks else None,
        assumptions=payload.assumptions,
        acceptance_criteria=payload.acceptance_criteria,
    )
    await session.commit()
    return MissionOut.model_validate(mission)


@router.get("/{mission_id}", response_model=MissionOut, summary="Mission detail")
async def get_mission(mission_id: str, auth: CurrentAuth, session: CurrentSession) -> MissionOut:
    auth.require("missions:read")
    mission = await mission_service.get_mission(session, auth.organization_id, mission_id)
    return MissionOut.model_validate(mission)


@router.get("/{mission_id}/tasks", response_model=list[TaskOut], summary="Mission tasks")
async def list_tasks(mission_id: str, auth: CurrentAuth, session: CurrentSession) -> list[TaskOut]:
    auth.require("missions:read")
    await mission_service.get_mission(session, auth.organization_id, mission_id)
    rows = await mission_service.list_tasks(session, mission_id)
    return [TaskOut.model_validate(row) for row in rows]


@router.get(
    "/{mission_id}/timeline",
    response_model=MissionTimeline,
    summary="The 8 computed workflow steps",
)
async def timeline(mission_id: str, auth: CurrentAuth, session: CurrentSession) -> MissionTimeline:
    """Each step's state is computed from real rows, never stored progress."""
    auth.require("missions:read")
    mission = await mission_service.get_mission(session, auth.organization_id, mission_id)
    return MissionTimeline(**await mission_service.build_timeline(session, mission))


@router.post("/tasks/{task_id}/claim", response_model=TaskOut, summary="Atomically claim a task")
async def claim_task(task_id: str, auth: CurrentAuth, session: CurrentSession) -> TaskOut:
    auth.require("missions:write")
    task = await mission_service.claim_task(
        session, organization_id=auth.organization_id, actor_id=auth.user.id, task_id=task_id
    )
    await session.commit()
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/complete", response_model=TaskOut, summary="Complete or fail a task")
async def complete_task(
    task_id: str,
    auth: CurrentAuth,
    session: CurrentSession,
    success: Annotated[bool, Query()] = True,
    error: Annotated[str | None, Query(max_length=600)] = None,
) -> TaskOut:
    auth.require("missions:write")
    task = await mission_service.complete_task(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        task_id=task_id,
        success=success,
        error=error,
    )
    await session.commit()
    return TaskOut.model_validate(task)


@pr_router.get("", response_model=list[PullRequestOut], summary="List pull requests")
async def list_pull_requests(
    auth: CurrentAuth, session: CurrentSession, mission_id: str | None = Query(default=None)
) -> list[PullRequestOut]:
    auth.require("missions:read")
    from sqlalchemy import select

    from app.models.collaboration import PullRequest

    conditions = [PullRequest.organization_id == auth.organization_id]
    if mission_id:
        conditions.append(PullRequest.mission_id == mission_id)
    rows = (await session.scalars(select(PullRequest).where(*conditions))).all()
    return [PullRequestOut.model_validate(row) for row in rows]


@pr_router.post(
    "",
    response_model=PullRequestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register an opened pull request",
    dependencies=[Depends(require("missions:write"))],
)
async def create_pull_request(
    payload: PullRequestCreate, auth: CurrentAuth, session: CurrentSession
) -> PullRequestOut:
    pull_request = await mission_service.register_pull_request(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        mission_id=payload.mission_id,
        task_id=payload.task_id,
        repository=payload.repository,
        number=payload.number,
        url=payload.url,
        title=payload.title,
        branch=payload.branch,
        base_branch=payload.base_branch,
        is_draft=payload.is_draft,
    )
    await session.commit()
    return PullRequestOut.model_validate(pull_request)


@pr_router.post(
    "/{pull_request_id}/reviews",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record an AI reviewer verdict (never an approval)",
)
async def create_review(
    pull_request_id: str, payload: ReviewCreate, auth: CurrentAuth, session: CurrentSession
) -> ReviewOut:
    auth.require("missions:write")
    review = await mission_service.record_review(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        pull_request_id=pull_request_id,
        verdict=payload.verdict,
        summary=payload.summary,
        reviewer_agent_id=payload.reviewer_agent_id,
        parse_attempts=payload.parse_attempts,
    )
    await session.commit()
    return ReviewOut.model_validate(review)


@pr_router.post(
    "/{pull_request_id}/merge",
    response_model=PullRequestOut,
    summary="Merge only with a human-approved merge Approval and green checks",
)
async def merge_pull_request(
    pull_request_id: str,
    auth: CurrentAuth,
    session: CurrentSession,
    approval_id: Annotated[str, Query(min_length=1, max_length=64)],
) -> PullRequestOut:
    auth.require("missions:write")
    pull_request = await mission_service.merge_pull_request(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        pull_request_id=pull_request_id,
        human_approval_id=approval_id,
    )
    await session.commit()
    return PullRequestOut.model_validate(pull_request)
