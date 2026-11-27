#!/usr/bin/env bash
#
# Project quality gate (docs/SPEC.md §9) for the slices present in this
# repository today: the FastAPI backend + conformance test suite.
#
# Runs:
#   1. ruff          — lint over backend/ and tests/
#   2. mypy (strict) — the security-critical packages (app/core, app/tools)
#   3. migrations    — `alembic upgrade head` + `downgrade -1` + `upgrade head`
#                      on an empty SQLite database (PostgreSQL parity is a
#                      documented gap — see the PR description)
#   4. pytest        — tests/test_spec_conformance.py (in-process against a
#                      throwaway SQLite database)
#   5. CI workflow   — node tests/ci/check-ci-workflow.mjs (when node exists)
#
# Every step must pass; the script fails on the first one that does not.
# IMPORTANT (E49): run the CI workflow check BEFORE opening a PR — see
# .github/workflows/ci.yml for the jobs that will execute remotely.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

PYTHON="${PYTHON:-python3}"
case "${PYTHON}" in
  /*) ;;                       # already absolute
  *) PYTHON="${ROOT}/${PYTHON}" ;;
esac

echo ":: ruff"
"${PYTHON}" -m ruff check backend tests

echo ":: mypy (strict on app/core + app/tools)"
"${PYTHON}" -m mypy

echo ":: Alembic migrations on an empty SQLite database (upgrade, downgrade -1, upgrade)"
TMP_DB="$(mktemp -d)/check.db"
export NEXUS_DATABASE_URL="sqlite+aiosqlite:///${TMP_DB}"
export NEXUS_JWT_SECRET="check-script-throwaway-secret-not-a-real-credential"
(cd backend && "${PYTHON}" -m alembic upgrade head)
(cd backend && "${PYTHON}" -m alembic downgrade -1)
(cd backend && "${PYTHON}" -m alembic upgrade head)

echo ":: pytest (SPEC conformance, in-process backend)"
"${PYTHON}" -m pytest -q tests/test_spec_conformance.py

if command -v node >/dev/null 2>&1; then
  echo ":: CI workflow validation"
  node tests/ci/check-ci-workflow.mjs
else
  echo ":: node not available — skipping the CI workflow validation step"
fi

echo "check.sh: all gates passed."
