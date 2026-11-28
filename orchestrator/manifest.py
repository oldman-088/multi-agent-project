"""Shared task manifest: reader and validator for task-register data.

This module is the single implementation of the task-manifest data schema that
Worker 4's orchestration engine shares with the execution tasks. The schema is
specified by the shared contract at exactly ``docs/ORCHESTRATION.md``
(:data:`CONTRACT_PATH`) — the orchestration engine must reference that exact
path, and no second task-manifest contract exists at any other path.

A task record has exactly five fields, as defined by the contract:

* ``id``           — unique task identifier (this project uses ``AATM-<uuid>``)
* ``title``        — short human-readable summary of the task
* ``assignee``     — the worker that owns execution (``unassigned`` when none)
* ``status``       — one of :data:`VALID_STATUSES`
* ``dependencies`` — ids of tasks that must complete before this one

A manifest document is a JSON object ``{"tasks": [...]}``. :func:`load_manifest`
reads such a document from disk; :func:`parse_manifest` and :func:`parse_task`
validate in-memory data and raise :class:`ManifestError` on any violation
(missing/unknown fields, bad status, duplicate ids, unknown dependency
references, self-references, dependency cycles).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The one shared task-manifest contract. The orchestration engine must
#: reference this exact path; it is intentionally the only contract location.
CONTRACT_PATH: str = "docs/ORCHESTRATION.md"

#: Allowed values of the ``status`` field (docs/ORCHESTRATION.md).
VALID_STATUSES: tuple[str, ...] = ("ready", "in_progress", "blocked", "done", "failed")

#: The five schema fields, in canonical order (docs/ORCHESTRATION.md).
SCHEMA_FIELDS: tuple[str, ...] = ("id", "title", "assignee", "status", "dependencies")

#: Literal used for tasks that have no designated owner.
UNASSIGNED: str = "unassigned"


class ManifestError(ValueError):
    """Raised when task data violates the task-manifest contract.

    The message always names the offending task or field so the orchestration
    engine can surface actionable errors to the execution tasks.
    """


@dataclass(frozen=True)
class Task:
    """One validated task record of the shared manifest."""

    id: str
    title: str
    assignee: str
    status: str
    dependencies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-serializable form defined by the contract."""
        return {
            "id": self.id,
            "title": self.title,
            "assignee": self.assignee,
            "status": self.status,
            "dependencies": list(self.dependencies),
        }


def _require_non_empty_str(value: object, field_name: str, context: str) -> str:
    if not isinstance(value, str):
        raise ManifestError(f"{context}.{field_name}: must be a string, got {type(value).__name__}")
    if not value.strip():
        raise ManifestError(f"{context}.{field_name}: must not be empty")
    return value


def parse_task(data: object, *, context: str = "task") -> Task:
    """Validate one task record against the contract schema.

    ``context`` is used in error messages (for example ``tasks[2]``).
    """
    if not isinstance(data, Mapping):
        raise ManifestError(f"{context}: must be an object, got {type(data).__name__}")

    unknown = sorted(set(data) - set(SCHEMA_FIELDS))
    if unknown:
        raise ManifestError(
            f"{context}: unknown field(s) {unknown}; the schema has exactly {list(SCHEMA_FIELDS)}"
        )
    missing = [field for field in SCHEMA_FIELDS if field not in data]
    if missing:
        raise ManifestError(f"{context}: missing required field(s) {missing}")

    task_id = _require_non_empty_str(data["id"], "id", context)
    title = _require_non_empty_str(data["title"], "title", context)
    assignee = _require_non_empty_str(data["assignee"], "assignee", context)

    status = data["status"]
    if not isinstance(status, str) or status not in VALID_STATUSES:
        raise ManifestError(
            f"{context}.status: must be one of {list(VALID_STATUSES)}, got {status!r}"
        )

    raw_deps = data["dependencies"]
    if not isinstance(raw_deps, list):
        raise ManifestError(
            f"{context}.dependencies: must be a list of task ids, got {type(raw_deps).__name__}"
        )
    dependencies: list[str] = []
    for index, dep in enumerate(raw_deps):
        dependencies.append(_require_non_empty_str(dep, f"dependencies[{index}]", context))
    if len(set(dependencies)) != len(dependencies):
        raise ManifestError(f"{context}.dependencies: duplicate dependency ids in {dependencies}")
    if task_id in dependencies:
        raise ManifestError(f"{context}.dependencies: task {task_id!r} cannot depend on itself")

    return Task(
        id=task_id,
        title=title,
        assignee=assignee,
        status=status,
        dependencies=tuple(dependencies),
    )


def _validate_graph(tasks: Sequence[Task]) -> None:
    """Validate cross-task rules: unique ids, known refs, no cycles."""
    seen: dict[str, int] = {}
    for index, task in enumerate(tasks):
        if task.id in seen:
            raise ManifestError(
                f"tasks[{index}]: duplicate task id {task.id!r} "
                f"(first seen at tasks[{seen[task.id]}])"
            )
        seen[task.id] = index

    for index, task in enumerate(tasks):
        for dep in task.dependencies:
            if dep not in seen:
                raise ManifestError(
                    f"tasks[{index}].dependencies: unknown task id {dep!r} "
                    f"(task {task.id!r} depends on a task that is not in the manifest)"
                )

    # Cycle detection (Kahn's algorithm); report the leftover walk on failure.
    dependents: dict[str, list[str]] = {task.id: [] for task in tasks}
    for task in tasks:
        for dep in task.dependencies:
            dependents[dep].append(task.id)
    remaining = {task.id: len(task.dependencies) for task in tasks}
    frontier = [task.id for task in tasks if not task.dependencies]
    visited = 0
    while frontier:
        current = frontier.pop()
        visited += 1
        for dependent in dependents[current]:
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                frontier.append(dependent)
    if visited != len(tasks):
        cyclic = sorted(task_id for task_id, count in remaining.items() if count > 0)
        raise ManifestError(f"dependencies form a cycle involving task(s): {cyclic}")


def parse_manifest(document: object) -> list[Task]:
    """Validate a manifest document (``{"tasks": [...]}``) and return its tasks."""
    if not isinstance(document, Mapping):
        raise ManifestError(
            f"manifest: must be an object with a 'tasks' list, got {type(document).__name__}"
        )
    unknown = sorted(set(document) - {"tasks"})
    if unknown:
        raise ManifestError(
            f"manifest: unknown field(s) {unknown}; the document has exactly ['tasks']"
        )
    if "tasks" not in document:
        raise ManifestError("manifest: missing required field 'tasks'")
    raw_tasks = document["tasks"]
    if not isinstance(raw_tasks, list):
        raise ManifestError(f"manifest.tasks: must be a list, got {type(raw_tasks).__name__}")

    tasks = [parse_task(item, context=f"tasks[{index}]") for index, item in enumerate(raw_tasks)]
    _validate_graph(tasks)
    return tasks


def load_manifest(path: str | Path) -> list[Task]:
    """Read a manifest JSON document from ``path`` and validate it."""
    manifest_path = Path(path)
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {manifest_path}: {exc}") from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{manifest_path}: invalid JSON: {exc}") from exc
    return parse_manifest(document)


def ready_tasks(tasks: Sequence[Task]) -> list[Task]:
    """Return the tasks whose status is ``ready`` (the manifest's ready set)."""
    return [task for task in tasks if task.status == "ready"]
