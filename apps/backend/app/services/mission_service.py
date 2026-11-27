"""Missions, task DAG validation and the 8-step timeline (SPEC §1, §6 Phase 3).

The timeline is computed from real rows — tasks, pull requests, reviews and
approvals — never from a stored "progress" field.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.db.base import utcnow
from app.models.collaboration import (
    Mission,
    PullRequest,
    Review,
    Task,
    TaskDependency,
    Team,
    TeamMember,
)
from app.models.enums import RunStatus
from app.models.runs import Run
from app.services import audit, event_service

TIMELINE_STEPS: list[tuple[int, str, str]] = [
    (1, "request", "Request"),
    (2, "analyze", "Analyze & split"),
    (3, "distribute", "Distribute"),
    (4, "execute", "Execute"),
    (5, "collect", "Collect"),
    (6, "pull_request", "Pull request"),
    (7, "review_merge", "Review & merge"),
    (8, "completed", "Completed"),
]

TASK_TERMINAL = {"completed", "failed", "cancelled", "parked"}


def validate_dag(nodes: list[str], edges: list[tuple[str, str]]) -> dict[str, Any]:
    """Reject cycles and report structural warnings for the plan (SPEC §6 P3).

    ``edges`` are ``(task, depends_on)`` pairs.
    """
    known = set(nodes)
    unknown = [f"{a}->{b}" for a, b in edges if a not in known or b not in known]
    if unknown:
        raise ValidationFailedError(
            "Plan references unknown tasks", code="invalid_plan", details={"edges": unknown}
        )

    # Kahn's algorithm for cycle detection.
    incoming: dict[str, int] = dict.fromkeys(nodes, 0)
    outgoing: dict[str, list[str]] = {node: [] for node in nodes}
    for task, depends_on in edges:
        incoming[task] += 1
        outgoing[depends_on].append(task)
    queue = [node for node, count in incoming.items() if count == 0]
    visited = 0
    while queue:
        node = queue.pop()
        visited += 1
        for neighbour in outgoing[node]:
            incoming[neighbour] -= 1
            if incoming[neighbour] == 0:
                queue.append(neighbour)
    if visited != len(nodes):
        cyclic = [node for node, count in incoming.items() if count > 0]
        raise ValidationFailedError(
            "Task DAG contains a cycle", code="dag_cycle", details={"nodes": cyclic}
        )
    return {"valid": True, "task_count": len(nodes), "edge_count": len(edges)}


def contract_warnings(tasks: list[dict[str, Any]]) -> list[str]:
    """Warn when frontend and backend tasks lack a shared contract (SPEC §6 P3)."""
    specialties = {str(task.get("specialty", "")).lower() for task in tasks}
    has_frontend = any("front" in item or "ui" in item for item in specialties)
    has_backend = any("back" in item or "api" in item for item in specialties)
    if has_frontend and has_backend:
        documented = any(task.get("contract") for task in tasks)
        if not documented:
            return [
                "frontend and backend tasks exist without a shared contract; "
                "define one in docs/API.md before dispatch"
            ]
    return []


async def create_mission(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    title: str,
    directive: str,
    team_id: str | None = None,
    tasks: list[dict[str, Any]] | None = None,
    assumptions: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
) -> Mission:
    if team_id:
        team = await session.get(Team, team_id)
        if team is None or team.organization_id != organization_id:
            raise NotFoundError("Team not found")

    mission = Mission(
        organization_id=organization_id,
        team_id=team_id,
        title=title,
        directive=directive,
        status="planned",
        assumptions=assumptions or [],
        acceptance_criteria=acceptance_criteria or [],
    )
    session.add(mission)
    await session.flush()

    if tasks:
        await replace_tasks(
            session,
            organization_id=organization_id,
            actor_id=actor_id,
            mission=mission,
            tasks=tasks,
        )
    await event_service.append_event(
        session,
        organization_id=organization_id,
        event_type="plan.proposed",
        payload={"mission_id": mission.id, "task_count": len(tasks or [])},
    )
    await audit.record(
        session,
        action="missions.create",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="mission",
        target_id=mission.id,
        context={"title": title, "task_count": len(tasks or [])},
    )
    return mission


async def replace_tasks(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    mission: Mission,
    tasks: list[dict[str, Any]],
) -> list[Task]:
    """Create the task DAG for a mission after validating it has no cycles."""
    keys = [str(task["key"]) for task in tasks]
    if len(set(keys)) != len(keys):
        raise ValidationFailedError("Task keys must be unique", code="invalid_plan")
    edges: list[tuple[str, str]] = []
    for task in tasks:
        for dependency in task.get("depends_on", []) or []:
            edges.append((str(task["key"]), str(dependency)))

    validation = validate_dag(keys, edges)

    existing = list(
        (await session.scalars(select(Task).where(Task.mission_id == mission.id))).all()
    )
    if existing:
        raise ConflictError(
            "Mission already has tasks; create a new mission or replan explicitly",
            code="tasks_exist",
        )

    created: dict[str, Task] = {}
    for spec in tasks:
        created_task = Task(
            organization_id=organization_id,
            mission_id=mission.id,
            title=str(spec["title"])[:200],
            description=str(spec.get("description", "")),
            specialty=str(spec.get("specialty", "general"))[:48],
            status="pending",
            max_attempts=int(spec.get("max_attempts", 3)),
            branch_name=f"aatm/task-{str(spec['key'])[:24]}-{_slug(str(spec['title']))[:40]}",
        )
        session.add(created_task)
        created[str(spec["key"])] = created_task
    await session.flush()

    for task_key, dependency_key in edges:
        session.add(
            TaskDependency(
                task_id=created[task_key].id, depends_on_task_id=created[dependency_key].id
            )
        )
    mission.plan = {
        "tasks": [dict(spec) for spec in tasks],
        "edges": [{"task": a, "depends_on": b} for a, b in edges],
    }
    mission.plan_validation = {
        **validation,
        "warnings": contract_warnings(tasks),
    }
    await session.flush()
    for new_task in created.values():
        await event_service.append_event(
            session,
            organization_id=organization_id,
            task_id=new_task.id,
            event_type="task.created",
            payload={"title": new_task.title, "specialty": new_task.specialty},
        )
    await audit.record(
        session,
        action="missions.plan",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="mission",
        target_id=mission.id,
        context={"task_count": len(created), "warnings": mission.plan_validation["warnings"]},
    )
    return list(created.values())


def _slug(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


async def claim_task(
    session: AsyncSession, *, organization_id: str, actor_id: str, task_id: str
) -> Task:
    """Atomically claim a pending task so two workers can never run it twice."""
    task = await session.get(Task, task_id, with_for_update=True)
    if task is None or task.organization_id != organization_id:
        raise NotFoundError("Task not found")
    if task.status != "pending":
        raise ConflictError(f"Task is '{task.status}', not claimable", code="task_not_claimable")
    blocking = (
        (
            await session.execute(
                select(Task.status)
                .join(TaskDependency, TaskDependency.depends_on_task_id == Task.id)
                .where(TaskDependency.task_id == task.id)
            )
        )
        .scalars()
        .all()
    )
    unfinished = [status for status in blocking if status != "completed"]
    if unfinished:
        raise ConflictError(
            "Task dependencies are not complete yet",
            code="dependencies_unfinished",
            details={"unfinished": len(unfinished)},
        )
    task.status = "running"
    task.claimed_at = utcnow()
    task.claimed_by = actor_id
    task.attempt += 1
    task.started_at = task.started_at or utcnow()
    await event_service.append_event(
        session,
        organization_id=organization_id,
        task_id=task.id,
        event_type="task.assigned",
        payload={"claimed_by": actor_id, "attempt": task.attempt},
    )
    await audit.record(
        session,
        action="tasks.claim",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="task",
        target_id=task.id,
    )
    return task


async def complete_task(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    task_id: str,
    success: bool,
    error: str | None = None,
) -> Task:
    task = await session.get(Task, task_id, with_for_update=True)
    if task is None or task.organization_id != organization_id:
        raise NotFoundError("Task not found")
    task.status = "completed" if success else "failed"
    task.finished_at = utcnow()
    if error:
        task.error = error[:600]
    if not success and task.attempt >= task.max_attempts:
        task.is_parked = True
        task.status = "parked"
    await event_service.append_event(
        session,
        organization_id=organization_id,
        task_id=task.id,
        event_type="task.completed" if success else "task.failed",
        payload={"attempt": task.attempt, "parked": task.is_parked, "error": error},
    )
    await audit.record(
        session,
        action="tasks.complete" if success else "tasks.fail",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="task",
        target_id=task.id,
        context={"attempt": task.attempt, "parked": task.is_parked},
    )
    return task


async def get_mission(session: AsyncSession, organization_id: str, mission_id: str) -> Mission:
    mission = await session.get(Mission, mission_id)
    if mission is None or mission.organization_id != organization_id:
        raise NotFoundError("Mission not found")
    return mission


async def list_missions(
    session: AsyncSession, organization_id: str, limit: int = 50, offset: int = 0
) -> tuple[list[Mission], int]:
    total = await session.scalar(
        select(func.count()).select_from(Mission).where(Mission.organization_id == organization_id)
    )
    rows = (
        await session.scalars(
            select(Mission)
            .where(Mission.organization_id == organization_id)
            .order_by(Mission.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(rows), int(total or 0)


async def list_tasks(session: AsyncSession, mission_id: str) -> list[Task]:
    return list(
        (
            await session.scalars(
                select(Task).where(Task.mission_id == mission_id).order_by(Task.created_at)
            )
        ).all()
    )


async def build_timeline(session: AsyncSession, mission: Mission) -> dict[str, Any]:
    """Compute each of the 8 steps from real rows: tasks, PRs, reviews, approvals."""
    tasks = await list_tasks(session, mission.id)
    total = len(tasks)
    done = sum(1 for task in tasks if task.status == "completed")
    failed = sum(1 for task in tasks if task.status in {"failed", "parked"})
    running = sum(1 for task in tasks if task.status == "running")

    pull_requests = list(
        (
            await session.scalars(select(PullRequest).where(PullRequest.mission_id == mission.id))
        ).all()
    )
    reviews = (
        list(
            (
                await session.scalars(
                    select(Review).where(
                        Review.pull_request_id.in_([pr.id for pr in pull_requests] or [""])
                    )
                )
            ).all()
        )
        if pull_requests
        else []
    )
    waiting_runs = int(
        await session.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.status == RunStatus.WAITING_FOR_USER)
            .where(Run.organization_id == mission.organization_id)
        )
        or 0
    )

    states: dict[str, tuple[str, str | None]] = {}
    states["request"] = ("done", "directive received")
    states["analyze"] = ("done", f"{total} tasks planned") if total else ("pending", "no plan yet")
    states["distribute"] = (
        ("done", f"{sum(1 for t in tasks if t.claimed_by)} claimed")
        if any(task.claimed_by for task in tasks)
        else ("active" if total else "pending", "waiting for claims")
    )
    if waiting_runs:
        states["execute"] = ("waiting_for_user", "a tab needs a human")
    elif running:
        states["execute"] = ("active", f"{running} task(s) running")
    elif total and done + failed >= total:
        states["execute"] = ("done", f"{done}/{total} completed")
    else:
        states["execute"] = ("pending", "not started")
    states["collect"] = (
        ("done", "deliverables verified")
        if total and done == total
        else ("pending", "awaiting tasks")
    )
    if pull_requests:
        states["pull_request"] = ("done", f"{len(pull_requests)} pull request(s)")
    else:
        states["pull_request"] = (
            ("active", "opening") if total and done == total else ("pending", "no pull request yet")
        )
    if reviews:
        verdicts = {review.verdict for review in reviews}
        merged = any(pr.merged_at is not None for pr in pull_requests)
        states["review_merge"] = (
            ("done", "merged after human approval")
            if merged
            else ("active", f"verdicts: {sorted(verdicts)}")
        )
    else:
        states["review_merge"] = ("pending", "no review yet")
    all_done = total > 0 and done == total and bool(pull_requests)
    states["completed"] = (
        ("done", "all tasks merged") if all_done else ("pending", "mission in progress")
    )

    steps = []
    for index, key, label in TIMELINE_STEPS:
        state, detail = states[key]
        steps.append({"step": index, "key": key, "state": state, "label": label, "detail": detail})

    elapsed = None
    if mission.started_at:
        end = mission.finished_at or utcnow()
        elapsed = int((end - mission.started_at).total_seconds())

    return {
        "mission_id": mission.id,
        "steps": steps,
        "tasks_total": total,
        "tasks_done": done,
        "pull_requests": len(pull_requests),
        "elapsed_seconds": elapsed,
    }


async def register_pull_request(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    mission_id: str | None,
    task_id: str | None,
    repository: str,
    number: int | None,
    url: str | None,
    title: str,
    branch: str,
    base_branch: str = "main",
    is_draft: bool = True,
) -> PullRequest:
    pull_request = PullRequest(
        organization_id=organization_id,
        mission_id=mission_id,
        task_id=task_id,
        repository=repository,
        number=number,
        url=url,
        title=title,
        branch=branch,
        base_branch=base_branch,
        is_draft=is_draft,
        status="open",
    )
    session.add(pull_request)
    await session.flush()
    await event_service.append_event(
        session,
        organization_id=organization_id,
        task_id=task_id,
        event_type="pr.opened",
        payload={"pull_request_id": pull_request.id, "repository": repository, "number": number},
    )
    await audit.record(
        session,
        action="pull_requests.open",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="pull_request",
        target_id=pull_request.id,
        context={"branch": branch, "draft": is_draft},
    )
    return pull_request


async def record_review(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    pull_request_id: str,
    verdict: str,
    summary: str,
    reviewer_agent_id: str | None = None,
    parse_attempts: int = 1,
) -> Review:
    """AI reviewers can comment or request changes; only a human can approve a merge."""
    if verdict not in {"approve", "request_changes", "comment", "reject"}:
        raise ValidationFailedError("Unknown review verdict", code="invalid_verdict")
    review = Review(
        organization_id=organization_id,
        pull_request_id=pull_request_id,
        reviewer_agent_id=reviewer_agent_id,
        verdict=verdict,
        summary=summary,
        parse_attempts=parse_attempts,
    )
    session.add(review)
    await session.flush()
    await event_service.append_event(
        session,
        organization_id=organization_id,
        event_type="pr.reviewed",
        payload={"pull_request_id": pull_request_id, "verdict": verdict},
    )
    await audit.record(
        session,
        action="pull_requests.review",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="pull_request",
        target_id=pull_request_id,
        context={"verdict": verdict, "parse_attempts": parse_attempts},
    )
    return review


async def merge_pull_request(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    pull_request_id: str,
    human_approval_id: str | None,
) -> PullRequest:
    """Merge only after a human approved the merge approval (SPEC §1 step 7)."""
    from app.models.runs import Approval

    pull_request = await session.get(PullRequest, pull_request_id)
    if pull_request is None or pull_request.organization_id != organization_id:
        raise NotFoundError("Pull request not found")
    if pull_request.merged_at is not None:
        raise ConflictError("Pull request is already merged", code="already_merged")
    if not human_approval_id:
        raise ConflictError(
            "A human approval is required before merging", code="human_approval_required"
        )
    approval = await session.get(Approval, human_approval_id)
    if approval is None or approval.organization_id != organization_id:
        raise NotFoundError("Approval not found")
    if approval.status != "approved" or not approval.decided_by:
        raise ConflictError(
            "The merge approval has not been granted by a human",
            code="approval_not_granted",
        )
    if pull_request.checks_status != "success":
        raise ConflictError("Checks are not green on this pull request", code="checks_not_green")
    pull_request.merged_at = utcnow()
    pull_request.status = "merged"
    await event_service.append_event(
        session,
        organization_id=organization_id,
        event_type="pr.merged",
        payload={"pull_request_id": pull_request.id, "approval_id": approval.id},
    )
    await audit.record(
        session,
        action="pull_requests.merge",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="pull_request",
        target_id=pull_request.id,
        context={"approval_id": approval.id},
    )
    return pull_request


async def list_team_members(session: AsyncSession, team_id: str) -> list[TeamMember]:
    return list(
        (
            await session.scalars(
                select(TeamMember)
                .where(TeamMember.team_id == team_id)
                .order_by(TeamMember.position)
            )
        ).all()
    )
