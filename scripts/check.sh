#!/usr/bin/env bash
# scripts/check.sh — the quality gate from docs/SPEC.md §9.
#
# Superset gate covering the slices that exist in this repository:
#
#   apps/backend  — orchestration slice (this repository's workflows engine):
#                   ruff (lint + format), mypy (strict), pytest, and the Alembic
#                   round-trip (upgrade head -> downgrade -1 -> upgrade head) on
#                   an empty SQLite database and — when NEXUS_TEST_POSTGRES_URL
#                   points at a disposable server — an empty PostgreSQL database.
#   backend       — backend slice, when present: its own ruff / mypy / pytest /
#                   migration gate (same commands as its CI in backend.yml).
#
# TypeScript, Playwright and i18n gates are added by the frontend slice; they
# are listed below as clearly-labelled pending steps rather than silently
# reported as passing.
#
# Usage:
#   scripts/check.sh                       # everything below
#   scripts/check.sh style|types|tests     # one gate family
#   scripts/check.sh migrations            # SQLite + PostgreSQL (PG when available)
#   scripts/check.sh migrations-sqlite     # SQLite only
#   scripts/check.sh migrations-postgres   # PostgreSQL only (requires the URL)
#
# Environment:
#   PYTHON                    interpreter to use (default: python3, or .venv)
#   NEXUS_TEST_POSTGRES_URL   disposable PostgreSQL server for the PG gates
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python3}"
if [[ -x ".venv/bin/python" ]]; then PYTHON="$REPO_ROOT/.venv/bin/python"; fi

ORCH_DIR="apps/backend"
BACKEND_DIR="backend"

MODE="${1:-all}"
RUN_STYLE=0
RUN_TYPES=0
RUN_TESTS=0
RUN_MIG_SQLITE=0
RUN_MIG_PG=0
case "$MODE" in
  all) RUN_STYLE=1; RUN_TYPES=1; RUN_TESTS=1; RUN_MIG_SQLITE=1; RUN_MIG_PG=1 ;;
  style) RUN_STYLE=1 ;;
  types) RUN_TYPES=1 ;;
  tests) RUN_TESTS=1 ;;
  migrations) RUN_MIG_SQLITE=1; RUN_MIG_PG=1 ;;
  migrations-sqlite) RUN_MIG_SQLITE=1 ;;
  migrations-postgres) RUN_MIG_PG=1 ;;
  *)
    echo "usage: scripts/check.sh [all|style|types|tests|migrations|migrations-sqlite|migrations-postgres]" >&2
    exit 2
    ;;
esac

# `python -m <tool> --version` proves the tool is importable in this interpreter.
as_module() {
  local module="$1"; shift
  "$PYTHON" -m "$module" "$@" >/dev/null 2>&1
}

run_module() {
  local label="$1"; shift
  echo "── ${label} ─────────────────────────────────────────────"
  if "$PYTHON" -m "$@"; then
    echo "✅ ${label}"
    return 0
  fi
  echo "❌ ${label}"
  FAILED=1
  return 1
}

run_module_in() {
  # Like run_module, but runs inside a slice directory.  Only the command runs
  # in the subshell, so the FAILED flag still reaches the caller.
  local dir="$1" label="$2"; shift 2
  echo "── ${label} ─────────────────────────────────────────────"
  if (cd "$dir" && "$PYTHON" -m "$@"); then
    echo "✅ ${label}"
  else
    echo "❌ ${label}"
    FAILED=1
  fi
}

reset_workflow_db() {
  # The SPEC §9 gate runs on an EMPTY database: drop both tables (idempotent)
  # so a reused local server starts the round-trip clean.
  "$PYTHON" -c "
import sqlalchemy, sys
engine = sqlalchemy.create_engine(sys.argv[1])
with engine.begin() as conn:
    conn.execute(sqlalchemy.text('DROP TABLE IF EXISTS workflow_tasks'))
    conn.execute(sqlalchemy.text('DROP TABLE IF EXISTS workflows_alembic_version'))
engine.dispose()
" "$1"
}

run_alembic_roundtrip() {
  # docs/SPEC.md §9: upgrade head on an empty DB, downgrade -1, upgrade head.
  local label="$1" url="$2"
  echo "── ${label} ─────────────────────────────────────────────"
  if reset_workflow_db "$url" &&
    (
      cd "$ORCH_DIR" &&
      WORKFLOWS_DATABASE_URL="$url" "$PYTHON" -m alembic upgrade head &&
      WORKFLOWS_DATABASE_URL="$url" "$PYTHON" -m alembic downgrade -1 &&
      WORKFLOWS_DATABASE_URL="$url" "$PYTHON" -m alembic upgrade head
    ); then
    echo "✅ ${label}"
  else
    echo "❌ ${label}"
    FAILED=1
  fi
}

FAILED=0

if [[ -d "$ORCH_DIR" ]]; then
  if [[ "$RUN_STYLE" -eq 1 ]]; then
    if as_module ruff --version; then
      run_module_in "$ORCH_DIR" "ruff check (apps/backend)" ruff check app tests migrations
      run_module_in "$ORCH_DIR" "ruff format --check (apps/backend)" ruff format --check app tests migrations
    else
      echo "⚠️  ruff not installed — skipping lint (install with: pip install -e 'apps/backend[dev]')"
      FAILED=1
    fi
  fi

  if [[ "$RUN_TYPES" -eq 1 ]]; then
    if as_module mypy --version; then
      run_module_in "$ORCH_DIR" "mypy strict (apps/backend/app/workflows)" mypy app/workflows
    else
      echo "❌ mypy not installed — the type gate cannot be skipped"
      FAILED=1
    fi
  fi

  if [[ "$RUN_TESTS" -eq 1 ]]; then
    if as_module pytest --version; then
      run_module_in "$ORCH_DIR" "pytest (apps/backend)" pytest -q
    else
      echo "❌ pytest not installed — the test gate cannot be skipped"
      FAILED=1
    fi
  fi

  if [[ "$RUN_MIG_SQLITE" -eq 1 ]]; then
    if as_module alembic --version; then
      MIG_SQLITE_URL="sqlite:///${TMPDIR:-/tmp}/nexus-check-$$.db"
      run_alembic_roundtrip "migrations (SQLite)" "$MIG_SQLITE_URL"
      rm -f "${TMPDIR:-/tmp}/nexus-check-$$.db"
    else
      echo "❌ alembic not installed — the migration gate cannot be skipped"
      FAILED=1
    fi
  fi

  if [[ "$RUN_MIG_PG" -eq 1 ]]; then
    if [[ -z "${NEXUS_TEST_POSTGRES_URL:-}" ]]; then
      if [[ "$MODE" == "migrations-postgres" ]]; then
        echo "❌ migrations (PostgreSQL): set NEXUS_TEST_POSTGRES_URL to a disposable server" >&2
        FAILED=1
      else
        echo "⏭️  migrations (PostgreSQL) — skipped: no disposable server URL."
        echo "    Set NEXUS_TEST_POSTGRES_URL to run this gate locally (CI runs it against postgres:16)."
      fi
    elif as_module alembic --version; then
      run_alembic_roundtrip "migrations (PostgreSQL)" "$NEXUS_TEST_POSTGRES_URL"
    else
      echo "❌ alembic not installed — the migration gate cannot be skipped"
      FAILED=1
    fi
  fi
else
  echo "⏭️  apps/backend is not present — orchestration gates skipped"
fi

# Backend slice (Worker 1): same commands as its own gate, only when the slice
# and its dependency stack are present.
if [[ -d "$BACKEND_DIR" && -f "pyproject.toml" ]] && as_module fastapi --version; then
  if [[ "$RUN_STYLE" -eq 1 ]] && as_module ruff --version; then
    run_module "ruff check (backend)" ruff check backend tests
    run_module "ruff format --check (backend)" ruff format --check backend/app tests
  fi
  if [[ "$RUN_TYPES" -eq 1 ]] && as_module mypy --version; then
    run_module "mypy (backend/app)" mypy backend/app
  fi
  if [[ "$RUN_TESTS" -eq 1 ]] && as_module pytest --version; then
    run_module "pytest (tests/)" pytest tests -q
  fi
  if [[ "$RUN_MIG_SQLITE" -eq 1 ]] && as_module pytest --version; then
    run_module "migrations (backend chain)" pytest tests/test_migrations.py -q
  fi
elif [[ -d "$BACKEND_DIR" ]]; then
  echo "⏭️  backend slice present but its dependencies are not installed — its gates skipped"
fi

# Gates owned by slices that are not in this repository yet.
echo "── pending slices ───────────────────────────────────────"
echo "⏭️  TypeScript eslint/tsc — frontend slice"
echo "⏭️  Playwright e2e + axe — frontend slice"
echo "⏭️  i18n missing-key check — frontend slice"
echo "⏭️  userscript build + adapter schema — userscript slice"
echo "⏭️  bridge health — bridge slice"

if [[ "$FAILED" -ne 0 ]]; then
  echo "CHECK FAILED"
  exit 1
fi
echo "CHECK PASSED"
