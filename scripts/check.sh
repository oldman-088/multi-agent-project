#!/usr/bin/env bash
# scripts/check.sh — the quality gate from docs/SPEC.md §9.
#
# Runs the checks that exist in this slice: ruff (lint + format), mypy, pytest and
# the Alembic round-trip. TypeScript, Playwright and i18n gates are added by the
# frontend slice; they are listed here as clearly-disabled steps rather than
# silently reported as passing.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python3}"
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then PYTHON="$REPO_ROOT/.venv/bin/python"
elif [[ -x "$REPO_ROOT/apps/backend/.venv/bin/python" ]]; then PYTHON="$REPO_ROOT/apps/backend/.venv/bin/python"
fi

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

FAILED=0

if as_module ruff --version; then
  pushd "$REPO_ROOT/apps/backend" >/dev/null
  run_module "ruff check" ruff check app tests
    run_module "ruff format --check" ruff format --check app tests
  popd >/dev/null
else
  echo "⚠️  ruff not installed — skipping lint (install with: pip install -e '.[test]')"
fi

if as_module mypy --version; then
  pushd "$REPO_ROOT/apps/backend" >/dev/null
  run_module "mypy (apps/backend/app)" mypy app
  popd >/dev/null
else
  echo "⚠️  mypy not installed — skipping type check"
fi

if as_module pytest --version; then
  pushd "$REPO_ROOT/apps/backend" >/dev/null
  run_module "pytest" pytest tests -q
  popd >/dev/null
else
  echo "❌ pytest not installed — the test gate cannot be skipped"
  FAILED=1
fi

# Migrations: the SQLite half always runs; the PostgreSQL half runs when a
# disposable server URL is supplied (SPEC §9 requires both).
if [[ -n "${NEXUS_TEST_POSTGRES_URL:-}" ]]; then
  echo "── migrations (SQLite + PostgreSQL) ─────────────────────"
else
  echo "── migrations (SQLite only; set NEXUS_TEST_POSTGRES_URL for the PostgreSQL gate) ──"
fi
if as_module pytest --version; then
  pushd "$REPO_ROOT/apps/backend" >/dev/null
  run_module "migrations" pytest tests/test_migrations.py -q
  popd >/dev/null
fi

# Gates owned by phases that are not in this slice.
echo "── not in this slice ────────────────────────────────────"
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
