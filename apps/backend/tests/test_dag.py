"""Tests for DAG validation: cycle rejection and ordering."""

from __future__ import annotations

import pytest

from app.workflows.dag import (
    TaskSpec,
    dependents_map,
    descendants,
    find_cycle,
    ready_tasks,
    validate_dag,
)
from app.workflows.errors import DAGCycleError, DuplicateTaskError, UnknownDependencyError


def spec(task_id: str, *deps: str) -> TaskSpec:
    return TaskSpec(task_id=task_id, depends_on=tuple(deps))


class TestValidateDag:
    def test_accepts_diamond_and_returns_topological_order(self) -> None:
        order = validate_dag([spec("a"), spec("b", "a"), spec("c", "a"), spec("d", "b", "c")])
        assert set(order) == {"a", "b", "c", "d"}
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")

    def test_accepts_empty_plan(self) -> None:
        assert validate_dag([]) == ()

    def test_accepts_mapping_form(self) -> None:
        order = validate_dag({"a": (), "b": ("a",)})
        assert order == ("a", "b")

    def test_rejects_self_cycle(self) -> None:
        with pytest.raises(DAGCycleError) as excinfo:
            validate_dag([spec("a", "a")])
        assert excinfo.value.cycle == ("a", "a")

    def test_rejects_two_node_cycle(self) -> None:
        with pytest.raises(DAGCycleError) as excinfo:
            validate_dag([spec("a", "b"), spec("b", "a")])
        cycle = excinfo.value.cycle
        assert cycle[0] == cycle[-1]
        assert set(cycle) == {"a", "b"}

    def test_rejects_long_cycle_and_reports_it(self) -> None:
        with pytest.raises(DAGCycleError) as excinfo:
            validate_dag([spec("a", "c"), spec("b", "a"), spec("c", "b")])
        cycle = excinfo.value.cycle
        assert cycle[0] == cycle[-1]
        assert set(cycle) == {"a", "b", "c"}

    def test_cycle_error_is_a_dag_validation_error(self) -> None:
        with pytest.raises(ValueError):
            validate_dag([spec("a", "b"), spec("b", "a")])

    def test_rejects_unknown_dependency(self) -> None:
        with pytest.raises(UnknownDependencyError) as excinfo:
            validate_dag([spec("a", "ghost")])
        assert excinfo.value.missing == "ghost"

    def test_rejects_duplicate_ids(self) -> None:
        with pytest.raises(DuplicateTaskError):
            validate_dag([spec("a"), spec("a", "b"), spec("b")])

    def test_order_is_deterministic(self) -> None:
        plan = [spec(f"t{i}") for i in range(5)]
        assert validate_dag(plan) == validate_dag(plan)
        assert validate_dag(plan) == ("t0", "t1", "t2", "t3", "t4")


class TestHelpers:
    def test_find_cycle_returns_none_for_dag(self) -> None:
        assert find_cycle([spec("a"), spec("b", "a")]) is None

    def test_descendants(self) -> None:
        graph = {"a": (), "b": ("a",), "c": ("b",), "d": ("a",)}
        assert descendants(graph, "a") == {"b", "c", "d"}
        assert descendants(graph, "b") == {"c"}
        assert descendants(graph, "d") == set()

    def test_dependents_map(self) -> None:
        graph = {"a": (), "b": ("a",), "c": ("a",)}
        assert dependents_map(graph)["a"] == ("b", "c")

    def test_ready_tasks(self) -> None:
        graph = {"a": (), "b": ("a",), "c": ("a",)}
        assert ready_tasks(graph, set()) == ("a",)
        assert ready_tasks(graph, {"a"}) == ("b", "c")
        assert ready_tasks(graph, {"a", "b"}) == ("c",)


class TestTaskSpecValidation:
    def test_rejects_empty_task_id(self) -> None:
        with pytest.raises(ValueError):
            TaskSpec(task_id="")

    def test_rejects_bad_max_attempts(self) -> None:
        with pytest.raises(ValueError):
            TaskSpec(task_id="a", max_attempts=0)

    def test_spec_self_dependency_raises_cycle(self) -> None:
        with pytest.raises(DAGCycleError):
            TaskSpec(task_id="a", depends_on=("a",))
