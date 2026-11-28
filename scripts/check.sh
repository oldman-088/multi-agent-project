#!/usr/bin/env bash
# scripts/check.sh — project quality gate (docs/SPEC.md §9) for the slices
# present in this repository.
#
# This version gates the shared task-manifest slice (`orchestrator/` +
# `tests/orchestrator/`, contract `docs/ORCHESTRATION.md`):
#   style   — ruff check + ruff format --check
#   types   — mypy (strict)
#   tests   — pytest
#
# Coordination note (parallel pull requests): PR #6 (AATM-c73bfd0e, Worker 4)
# brings a superset gate covering apps/backend (ruff/mypy/pytest/Alembic) plus
# a `backend/` slice section whose `pytest tests` line also collects
# `tests/orchestrator/` once that slice exists. If this file conflicts at merge
# time, keep PR #6's version and ensure `python -m pytest tests/orchestrator`
# is part of its test gate.
#
# Usage:
#   scripts/check.sh            # style + types + tests
#   scripts/check.sh style      # lint + format only
#   scripts/check.sh types      # mypy only
#   scripts/check.sh tests      # pytest only
#
# Environment:
#   PYTHON   interpreter to use (default: python3, or .venv when present)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python3}"
if [[ -x ".venv/bin/python" ]]; then PYTHON="$REPO_ROOT/.venv/bin/python"; fi

MODE="${1:-all}"
case "$MODE" in
  all|style|types|tests) ;;
  *)
    echo "usage: scripts/check.sh [all|style|types|tests]" >&2
    exit 2
    ;;
esac

run() {
  local label="$1"; shift
  echo "── ${label} ─────────────────────────────────────────────"
  "$PYTHON" -m "$@"
}

if [[ "$MODE" == "all" || "$MODE" == "style" ]]; then
  run "ruff check (orchestrator, tests/orchestrator)" ruff check orchestrator tests/orchestrator
  run "ruff format --check (orchestrator, tests/orchestrator)" ruff format --check orchestrator tests/orchestrator
fi

if [[ "$MODE" == "all" || "$MODE" == "types" ]]; then
  run "mypy strict (orchestrator)" mypy orchestrator
fi

if [[ "$MODE" == "all" || "$MODE" == "tests" ]]; then
  run "pytest (tests/orchestrator)" pytest tests/orchestrator -q
fi

echo "CHECK PASSED"
