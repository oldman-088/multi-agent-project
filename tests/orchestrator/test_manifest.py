"""Tests for the shared task manifest and its contract (docs/ORCHESTRATION.md).

Three kinds of coverage:
1. ``orchestrator/manifest.py`` behaviour — the schema is enforced and the
   register data is read and validated exactly as the contract demands.
2. Contract ↔ implementation lockstep — every field and status documented in
   ``docs/ORCHESTRATION.md`` matches the implementation, and every example in
   the contract validates with the reference validator.
3. Coverage rules — the contract covers all currently ready tasks of the
   project with their ids and dependencies, and no second task-manifest
   contract exists at any other path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator import manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "docs" / "ORCHESTRATION.md"


def contract_text() -> str:
    return CONTRACT_PATH.read_text(encoding="utf-8")


def json_blocks(text: str) -> list[str]:
    """Return the content of every fenced ```json block in a markdown document."""
    blocks: list[str] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip() == "```json":
            index += 1
            start = index
            while index < len(lines) and lines[index].strip() != "```":
                index += 1
            blocks.append("\n".join(lines[start:index]))
        index += 1
    return blocks


def sample_task(**overrides: object) -> dict[str, object]:
    task: dict[str, object] = {
        "id": "AATM-00000000-0000-0000-0000-000000000000",
        "title": "Example task",
        "assignee": "worker-1",
        "status": "ready",
        "dependencies": [],
    }
    task.update(overrides)
    return task


# ---------------------------------------------------------------------------
# 1. orchestrator/manifest.py behaviour
# ---------------------------------------------------------------------------


class TestParseTask:
    def test_accepts_valid_record_and_round_trips(self) -> None:
        task = manifest.parse_task(sample_task())
        assert task.id == "AATM-00000000-0000-0000-0000-000000000000"
        assert task.title == "Example task"
        assert task.assignee == "worker-1"
        assert task.status == "ready"
        assert task.dependencies == ()
        assert manifest.parse_task(task.to_dict()) == task

    def test_accepts_non_empty_dependencies(self) -> None:
        task = manifest.parse_task(
            sample_task(dependencies=["AATM-11111111-1111-1111-1111-111111111111"])
        )
        assert task.dependencies == ("AATM-11111111-1111-1111-1111-111111111111",)

    @pytest.mark.parametrize("field", ["id", "title", "assignee", "status", "dependencies"])
    def test_rejects_missing_field(self, field: str) -> None:
        data = sample_task()
        del data[field]
        with pytest.raises(manifest.ManifestError, match="missing required field"):
            manifest.parse_task(data)

    def test_rejects_unknown_field(self) -> None:
        with pytest.raises(manifest.ManifestError, match="unknown field"):
            manifest.parse_task(sample_task(extra="nope"))

    @pytest.mark.parametrize("field", ["id", "title", "assignee"])
    def test_rejects_empty_string(self, field: str) -> None:
        with pytest.raises(manifest.ManifestError, match=f"{field}: must not be empty"):
            manifest.parse_task(sample_task(**{field: ""}))

    @pytest.mark.parametrize("field", ["id", "title", "assignee"])
    def test_rejects_non_string(self, field: str) -> None:
        with pytest.raises(manifest.ManifestError, match=f"{field}: must be a string"):
            manifest.parse_task(sample_task(**{field: 42}))

    def test_rejects_status_outside_the_allowed_values(self) -> None:
        with pytest.raises(manifest.ManifestError, match="must be one of"):
            manifest.parse_task(sample_task(status="queued"))

    def test_rejects_non_list_dependencies(self) -> None:
        with pytest.raises(manifest.ManifestError, match="dependencies: must be a list"):
            manifest.parse_task(sample_task(dependencies="AATM-1"))

    def test_rejects_duplicate_dependency(self) -> None:
        with pytest.raises(manifest.ManifestError, match="duplicate dependency"):
            manifest.parse_task(sample_task(dependencies=["A", "A"]))

    def test_rejects_self_dependency(self) -> None:
        task_id = "AATM-22222222-2222-2222-2222-222222222222"
        with pytest.raises(manifest.ManifestError, match="cannot depend on itself"):
            manifest.parse_task(sample_task(id=task_id, dependencies=[task_id]))

    def test_rejects_non_object(self) -> None:
        with pytest.raises(manifest.ManifestError, match="must be an object"):
            manifest.parse_task("not a task")

    def test_error_messages_name_the_context(self) -> None:
        with pytest.raises(manifest.ManifestError, match=r"tasks\[3\]\.status"):
            manifest.parse_task(sample_task(status="queued"), context="tasks[3]")


class TestParseManifest:
    def _document(self, *tasks: dict[str, object]) -> dict[str, object]:
        return {"tasks": list(tasks)}

    def test_accepts_valid_manifest(self) -> None:
        tasks = manifest.parse_manifest(self._document(sample_task()))
        assert len(tasks) == 1

    def test_rejects_non_object_document(self) -> None:
        with pytest.raises(manifest.ManifestError, match="must be an object"):
            manifest.parse_manifest([sample_task()])

    def test_rejects_missing_tasks_key(self) -> None:
        with pytest.raises(manifest.ManifestError, match="missing required field 'tasks'"):
            manifest.parse_manifest({})

    def test_rejects_unknown_top_level_field(self) -> None:
        with pytest.raises(manifest.ManifestError, match="unknown field"):
            manifest.parse_manifest({"tasks": [], "extra": 1})

    def test_rejects_tasks_not_a_list(self) -> None:
        with pytest.raises(manifest.ManifestError, match="manifest.tasks: must be a list"):
            manifest.parse_manifest({"tasks": {}})

    def test_rejects_duplicate_ids(self) -> None:
        with pytest.raises(manifest.ManifestError, match="duplicate task id"):
            manifest.parse_manifest(self._document(sample_task(), sample_task()))

    def test_rejects_unknown_dependency_reference(self) -> None:
        other = "AATM-33333333-3333-3333-3333-333333333333"
        with pytest.raises(manifest.ManifestError, match="unknown task id"):
            manifest.parse_manifest(self._document(sample_task(dependencies=[other])))

    def test_rejects_two_task_cycle(self) -> None:
        a = "AATM-aaaaaaaa-0000-0000-0000-000000000000"
        b = "AATM-bbbbbbbb-0000-0000-0000-000000000000"
        with pytest.raises(manifest.ManifestError, match="cycle"):
            manifest.parse_manifest(
                self._document(
                    sample_task(id=a, dependencies=[b]),
                    sample_task(id=b, dependencies=[a]),
                )
            )

    def test_rejects_three_task_cycle(self) -> None:
        a = "AATM-aaaaaaaa-0000-0000-0000-000000000000"
        b = "AATM-bbbbbbbb-0000-0000-0000-000000000000"
        c = "AATM-cccccccc-0000-0000-0000-000000000000"
        with pytest.raises(manifest.ManifestError, match="cycle"):
            manifest.parse_manifest(
                self._document(
                    sample_task(id=a, dependencies=[c]),
                    sample_task(id=b, dependencies=[a]),
                    sample_task(id=c, dependencies=[b]),
                )
            )

    def test_accepts_diamond_dependency_graph(self) -> None:
        a = "AATM-aaaaaaaa-0000-0000-0000-000000000000"
        b = "AATM-bbbbbbbb-0000-0000-0000-000000000000"
        c = "AATM-cccccccc-0000-0000-0000-000000000000"
        d = "AATM-dddddddd-0000-0000-0000-000000000000"
        tasks = manifest.parse_manifest(
            self._document(
                sample_task(id=a),
                sample_task(id=b, dependencies=[a]),
                sample_task(id=c, dependencies=[a]),
                sample_task(id=d, dependencies=[b, c]),
            )
        )
        assert [task.id for task in tasks] == [a, b, c, d]


class TestLoadManifest:
    def test_reads_and_validates_a_json_document(self, tmp_path: Path) -> None:
        path = tmp_path / "tasks.json"
        path.write_text(json.dumps({"tasks": [sample_task()]}), encoding="utf-8")
        tasks = manifest.load_manifest(path)
        assert [task.id for task in tasks] == ["AATM-00000000-0000-0000-0000-000000000000"]

    def test_rejects_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "tasks.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(manifest.ManifestError, match="invalid JSON"):
            manifest.load_manifest(path)

    def test_rejects_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(manifest.ManifestError, match="cannot read manifest"):
            manifest.load_manifest(tmp_path / "absent.json")

    def test_reports_the_file_and_task_context_on_invalid_data(self, tmp_path: Path) -> None:
        path = tmp_path / "tasks.json"
        path.write_text(json.dumps({"tasks": [sample_task(status="queued")]}), encoding="utf-8")
        with pytest.raises(manifest.ManifestError, match=r"tasks\[0\]\.status"):
            manifest.load_manifest(path)


class TestReadyTasks:
    def test_returns_only_ready_tasks(self) -> None:
        tasks = [
            manifest.parse_task(sample_task(status="ready")),
            manifest.parse_task(sample_task(id="AATM-4", status="in_progress")),
            manifest.parse_task(sample_task(id="AATM-5", status="done")),
            manifest.parse_task(sample_task(id="AATM-6", status="ready")),
        ]
        assert [task.id for task in manifest.ready_tasks(tasks)] == [
            "AATM-00000000-0000-0000-0000-000000000000",
            "AATM-6",
        ]


# ---------------------------------------------------------------------------
# 2. Contract ↔ implementation lockstep
# ---------------------------------------------------------------------------


class TestContractLockstep:
    def test_contract_path_is_the_exact_shared_path(self) -> None:
        assert manifest.CONTRACT_PATH == "docs/ORCHESTRATION.md"
        assert (REPO_ROOT / manifest.CONTRACT_PATH).is_file()

    def test_contract_names_the_exact_path_the_engine_must_reference(self) -> None:
        assert "docs/ORCHESTRATION.md" in contract_text()

    def test_contract_documents_every_schema_field(self) -> None:
        text = contract_text()
        for field in manifest.SCHEMA_FIELDS:
            assert f"| {field} |" in text, f"contract does not document field {field!r}"

    def test_contract_status_table_matches_valid_statuses(self) -> None:
        text = contract_text()
        section = text.split("## 3. Allowed status values", 1)[1].split("## 4.", 1)[0]
        documented = []
        for line in section.splitlines():
            if line.startswith("|") and not line.startswith("|---") and "status" not in line:
                documented.append(line.split("|")[1].strip())
        assert tuple(documented) == manifest.VALID_STATUSES

    def test_every_allowed_status_appears_in_the_contract(self) -> None:
        text = contract_text()
        for status in manifest.VALID_STATUSES:
            assert f"| {status} |" in text

    def test_every_contract_example_validates_with_the_reference_validator(self) -> None:
        blocks = json_blocks(contract_text())
        assert blocks, "the contract must contain JSON examples"
        for block in blocks:
            document = json.loads(block)
            if isinstance(document, dict) and set(document) == {"tasks"}:
                manifest.parse_manifest(document)
            else:
                manifest.parse_task(document)

    def test_manifest_module_references_the_contract_path(self) -> None:
        source = (REPO_ROOT / "orchestrator" / "manifest.py").read_text(encoding="utf-8")
        assert 'CONTRACT_PATH: str = "docs/ORCHESTRATION.md"' in source


# ---------------------------------------------------------------------------
# 3. Coverage rules
# ---------------------------------------------------------------------------


class TestContractCoverage:
    def _register_and_ready_blocks(self) -> tuple[dict[str, object], dict[str, object]]:
        blocks = [json.loads(block) for block in json_blocks(contract_text())]
        registers = [
            block
            for block in blocks
            if isinstance(block, dict)
            and set(block) == {"tasks"}
            and any(task["status"] != "ready" for task in block["tasks"])
        ]
        ready_sets = [
            block
            for block in blocks
            if isinstance(block, dict)
            and set(block) == {"tasks"}
            and block["tasks"]
            and all(task["status"] == "ready" for task in block["tasks"])
        ]
        assert len(registers) == 1, "the contract must contain one full register snapshot"
        assert len(ready_sets) == 1, "the contract must contain one currently-ready example"
        return registers[0], ready_sets[0]

    def test_contract_covers_all_currently_ready_tasks_with_ids_and_dependencies(self) -> None:
        register, ready_block = self._register_and_ready_blocks()
        register_tasks = manifest.parse_manifest(register)
        ready_tasks = manifest.parse_manifest(ready_block)

        ready_from_register = {task.id: task for task in manifest.ready_tasks(register_tasks)}
        ready_from_block = {task.id: task for task in ready_tasks}

        # Coverage in both directions: the ready example lists exactly the
        # register's ready tasks — all of them ("all currently ready tasks"),
        # and nothing that is not ready.
        assert ready_from_block == ready_from_register

        # Each covered task carries its id and its dependencies list.
        raw_ready = {task["id"]: task for task in ready_block["tasks"]}
        for task_id, task in raw_ready.items():
            assert "dependencies" in task, f"ready task {task_id} is missing its dependencies"
        for task_id, task in ready_from_register.items():
            assert raw_ready[task_id]["dependencies"] == list(task.dependencies)

    def test_full_register_snapshot_covers_every_status_the_project_uses(self) -> None:
        register, _ = self._register_and_ready_blocks()
        tasks = manifest.parse_manifest(register)
        statuses = {task.status for task in tasks}
        assert "ready" in statuses and "done" in statuses and "in_progress" in statuses

    def test_dependency_lists_only_reference_tasks_in_the_register(self) -> None:
        register, _ = self._register_and_ready_blocks()
        manifest.parse_manifest(register)  # raises on unknown refs / cycles


class TestSingleContract:
    def test_no_second_task_manifest_contract_at_any_other_path(self) -> None:
        marker = "# Task Manifest Contract"
        hits = [
            path
            for path in REPO_ROOT.rglob("*.md")
            if ".git" not in path.parts and marker in path.read_text(encoding="utf-8")
        ]
        assert hits == [CONTRACT_PATH], (
            "the task-manifest contract must exist only at docs/ORCHESTRATION.md; "
            f"also found at {hits}"
        )
