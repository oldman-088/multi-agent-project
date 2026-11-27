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
BACKEND_DIR = REPO_ROOT
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


def test_migration_history_is_a_single_linear_head() -> None:
    """One head, one base and no branch points: ``upgrade head`` is unambiguous."""
    import importlib.util

    version_dir = BACKEND_DIR / "alembic" / "versions"
    revisions: dict[str, str | None] = {}
    for path in sorted(version_dir.glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"_migration_{path.stem}", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        revisions[module.revision] = module.down_revision

    parents = {down for down in revisions.values() if down is not None}
    heads = sorted(set(revisions) - parents)
    bases = sorted(rev for rev, down in revisions.items() if down is None)
    assert len(heads) == 1, f"expected a single head revision, found {heads}"
    assert bases == ["0001_initial"], f"expected one base revision, found {bases}"
    # Every revision except the base must have exactly one child: no branches.
    for revision in revisions:
        children = [rev for rev, down in revisions.items() if down == revision]
        assert len(children) <= 1, f"revision {revision} is a branch point: {children}"


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
