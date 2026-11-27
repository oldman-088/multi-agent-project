"""Migration gate: one revision must apply to an empty SQLite and PostgreSQL DB (SPEC §9).

The PostgreSQL half is skipped with an explicit reason when no server is available,
as allowed by SPEC §6 Phase 5 ("if Docker is unavailable, report this phase as
blocked; do not fake it") applied to the database gate. A test run that does not
have PostgreSQL says so instead of silently passing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
ALEMBIC = [sys.executable, "-m", "alembic"]


def _run_alembic(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, NEXUS_DATABASE_URL=url)
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [*ALEMBIC, *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_single_migration_revision_exists() -> None:
    versions = sorted((BACKEND_DIR / "alembic" / "versions").glob("*.py"))
    assert [path.name for path in versions] == ["0001_initial_schema.py"], (
        "there must be exactly one head revision owned by the backend task"
    )


def test_migration_round_trips_on_empty_sqlite(tmp_path: Path) -> None:
    """upgrade head → downgrade base → upgrade head on an empty SQLite file."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"

    upgrade = _run_alembic(url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    import sqlite3

    connection = sqlite3.connect(tmp_path / "migration.db")
    try:
        tables = {
            row[0]
            for row in connection.execute("select name from sqlite_master where type='table'")
        }
    finally:
        connection.close()
    assert {"users", "agents", "runs", "events", "audit_logs", "approvals"} <= tables
    assert "alembic_version" in tables

    downgrade = _run_alembic(url, "downgrade", "base")
    assert downgrade.returncode == 0, downgrade.stderr

    connection = sqlite3.connect(tmp_path / "migration.db")
    try:
        remaining = {
            row[0]
            for row in connection.execute("select name from sqlite_master where type='table'")
        }
    finally:
        connection.close()
    assert remaining <= {"alembic_version"}

    reupgrade = _run_alembic(url, "upgrade", "head")
    assert reupgrade.returncode == 0, reupgrade.stderr


def _postgres_url_or_skip() -> str:
    url = os.environ.get("NEXUS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip(
            "PostgreSQL gate not exercised: set NEXUS_TEST_POSTGRES_URL to a disposable "
            "database (e.g. postgresql+asyncpg://user:pass@127.0.0.1:5432/nexus_ci). "
            "This is reported as a limitation, not as a pass."
        )
    return url


def test_migration_round_trips_on_empty_postgresql() -> None:
    """The same revision must apply to an empty PostgreSQL 16 database."""
    url = _postgres_url_or_skip()

    upgrade = _run_alembic(url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    downgrade = _run_alembic(url, "downgrade", "base")
    assert downgrade.returncode == 0, downgrade.stderr

    reupgrade = _run_alembic(url, "upgrade", "head")
    assert reupgrade.returncode == 0, reupgrade.stderr
