"""Task dependency graph: specs, cycle validation and ordering.

``validate_dag`` is the plan gate required by docs/SPEC.md (Phase 3): "a
coordinator decomposes a mission into a task DAG.  Validate that the DAG has no
cycles".  It raises :class:`~app.workflows.errors.DAGCycleError` with the
concrete cycle, so the planner can fix the plan instead of deadlocking.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .errors import DAGCycleError, DuplicateTaskError, UnknownDependencyError


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """One unit of work in a workflow plan.

    Attributes:
        task_id: Unique id inside the plan (and inside one workflow's store).
        depends_on: Ids of tasks that must succeed before this one may run.
        payload: Free-form data handed to the executor.
        max_attempts: Per-task attempt cap; ``None`` uses the run's RetryPolicy.
        kind: Execution class used for per-kind circuit breakers.
    """

    task_id: str
    depends_on: tuple[str, ...] = ()
    payload: Mapping[str, Any] = field(default_factory=dict)
    max_attempts: int | None = None
    kind: str = "default"

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id:
            raise ValueError("task_id must be a non-empty string")
        if not isinstance(self.kind, str) or not self.kind:
            raise ValueError("kind must be a non-empty string")
        for dep in self.depends_on:
            if not isinstance(dep, str) or not dep:
                raise ValueError(f"depends_on entries must be non-empty strings: {dep!r}")
        if self.task_id in self.depends_on:
            raise DAGCycleError((self.task_id, self.task_id))
        if self.max_attempts is not None and (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise ValueError(f"max_attempts must be None or an int >= 1, got {self.max_attempts!r}")


TaskGraph = Mapping[str, tuple[str, ...]]


def dependency_map(tasks: Iterable[TaskSpec]) -> dict[str, tuple[str, ...]]:
    """Build ``task_id -> dependency ids`` from specs, rejecting duplicates."""
    graph: dict[str, tuple[str, ...]] = {}
    for spec in tasks:
        if spec.task_id in graph:
            raise DuplicateTaskError(spec.task_id)
        graph[spec.task_id] = tuple(spec.depends_on)
    return graph


def _normalize(tasks: TaskGraph | Iterable[TaskSpec]) -> dict[str, tuple[str, ...]]:
    if isinstance(tasks, Mapping):
        graph = {str(key): tuple(deps) for key, deps in tasks.items()}
    else:
        graph = dependency_map(tasks)
    for task_id, deps in graph.items():
        if task_id in deps:
            raise DAGCycleError((task_id, task_id))
        for dep in deps:
            if dep not in graph:
                raise UnknownDependencyError(task_id, dep)
    return graph


def find_cycle(graph: TaskGraph | Iterable[TaskSpec]) -> tuple[str, ...] | None:
    """Return one cycle as a closed walk (e.g. ``("a", "b", "a")``), or ``None``.

    Iterative DFS (explicit stack) so a long dependency chain up to the
    ``max_tasks`` hard cap cannot hit Python's recursion limit.
    """
    normalized = _normalize(graph)
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(normalized, WHITE)

    for start in sorted(normalized):
        if color[start] != WHITE:
            continue
        color[start] = GREY
        path: list[str] = [start]
        on_path: dict[str, int] = {start: 0}
        stack: list[tuple[str, int]] = [(start, 0)]  # (node, next dependency index)
        while stack:
            node, index = stack[-1]
            deps = normalized[node]
            if index < len(deps):
                stack[-1] = (node, index + 1)
                dep = deps[index]
                if color[dep] == GREY:
                    return tuple(path[on_path[dep] :]) + (dep,)
                if color[dep] == WHITE:
                    color[dep] = GREY
                    on_path[dep] = len(path)
                    path.append(dep)
                    stack.append((dep, 0))
            else:
                stack.pop()
                color[node] = BLACK
                path.pop()
                on_path.pop(node)
    return None


def validate_dag(tasks: TaskGraph | Iterable[TaskSpec]) -> tuple[str, ...]:
    """Validate that the task graph is acyclic and return a topological order.

    Checks, in order: duplicate ids, self-cycles (in ``TaskSpec``), unknown
    dependency ids, and any longer cycle.

    Raises:
        DuplicateTaskError: Two specs share a task id.
        UnknownDependencyError: A dependency id is missing from the plan.
        DAGCycleError: The graph contains a cycle (the error carries the cycle).

    Returns:
        A deterministic topological order of the task ids.
    """
    graph = _normalize(tasks)
    cycle = find_cycle(graph)
    if cycle is not None:
        raise DAGCycleError(cycle)

    indegree = dict.fromkeys(graph, 0)
    dependents: dict[str, list[str]] = {node: [] for node in graph}
    for node, deps in graph.items():
        for dep in deps:
            dependents[dep].append(node)
            indegree[node] += 1
    ready = sorted(node for node, deg in indegree.items() if deg == 0)
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for dependent in sorted(dependents[node]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
        ready.sort()
    return tuple(order)


def dependents_map(graph: TaskGraph) -> dict[str, tuple[str, ...]]:
    """Reverse edges: ``task_id -> tasks that depend on it``."""
    dependents: dict[str, list[str]] = {node: [] for node in graph}
    for node, deps in graph.items():
        for dep in deps:
            dependents[dep].append(node)
    return {node: tuple(sorted(items)) for node, items in dependents.items()}


def descendants(graph: TaskGraph, root: str) -> set[str]:
    """Every task that transitively depends on ``root`` (``root`` excluded)."""
    if root not in graph:
        raise UnknownDependencyError("<descendants>", root)
    dependents = dependents_map(graph)
    seen: set[str] = set()
    frontier = list(dependents[root])
    while frontier:
        node = frontier.pop()
        if node in seen:
            continue
        seen.add(node)
        frontier.extend(dependents[node])
    return seen


def ready_tasks(graph: TaskGraph, succeeded: Collection[str]) -> tuple[str, ...]:
    """Tasks whose dependencies all appear in ``succeeded`` (stable order)."""
    done = set(succeeded)
    return tuple(
        node
        for node in sorted(graph)
        if node not in done and all(dep in done for dep in graph[node])
    )
