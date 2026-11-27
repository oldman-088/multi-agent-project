"""Migration gate (docs/SPEC.md §9): the revision round-trips on empty databases.

``upgrade head`` → ``downgrade -1`` → ``upgrade head`` must work on an empty
SQLite database *and* an empty PostgreSQL database.  The PostgreSQL half runs
when ``NEXUS_TEST_POSTGRES_URL`` is set (CI sets it against a postgres:16
service); otherwise it is skipped with that explicit reason instead of
silently passing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC = [sys.executable, "-m", "alembic"]


def _run_alembic(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, WORKFLOWS_DATABASE_URL=url)
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [*ALEMBIC, *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _table_names_sqlite(path: Path) -> set[str]:
    import sqlite3

    connection = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in connection.execute("select name from sqlite_master where type='table'")
        }
    finally:
        connection.close()


def _assert_schema_present(url: str, names: set[str]) -> None:
    assert "workflow_tasks" in names, names
    assert "workflows_alembic_version" in names, names


def test_single_revision_owned_by_this_slice() -> None:
    versions = sorted((BACKEND_DIR / "migrations" / "versions").glob("*.py"))
    assert [path.name for path in versions] == ["0001_workflow_tasks.py"]


def test_round_trip_on_empty_sqlite(tmp_path: Path) -> None:
    db = tmp_path / "migration.db"
    url = f"sqlite:///{db}"

    upgrade = _run_alembic(url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr
    names = _table_names_sqlite(db)
    _assert_schema_present(url, names)

    downgrade = _run_alembic(url, "downgrade", "-1")
    assert downgrade.returncode == 0, downgrade.stderr
    names = _table_names_sqlite(db)
    assert "workflow_tasks" not in names

    re_upgrade = _run_alembic(url, "upgrade", "head")
    assert re_upgrade.returncode == 0, re_upgrade.stderr
    assert "workflow_tasks" in _table_names_sqlite(db)


def test_migration_matches_the_sqlalchemy_model(tmp_path: Path) -> None:
    """The migrated table must expose exactly the model's columns."""
    from sqlalchemy import create_engine, inspect

    from app.workflows.models import WorkflowTaskRecord

    db = tmp_path / "parity.db"
    url = f"sqlite:///{db}"
    upgrade = _run_alembic(url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    engine = create_engine(url)
    try:
        migrated = {column["name"] for column in inspect(engine).get_columns("workflow_tasks")}
    finally:
        engine.dispose()
    expected = {column.name for column in WorkflowTaskRecord.__table__.columns}
    assert migrated == expected


def test_migration_matches_the_model_on_postgres() -> None:
    """PostgreSQL half of the migration gate (SPEC §9).

    Skipped with an explicit reason when no disposable PostgreSQL server URL is
    available (see the module docstring).
    """
    pytest.importorskip("psycopg", reason="psycopg (postgres extra) is not installed")
    url = os.environ.get("NEXUS_TEST_POSTGRES_URL") or os.environ.get("WORKFLOWS_DATABASE_URL_PG")
    if not url:
        pytest.skip(
            "PostgreSQL migration gate: set NEXUS_TEST_POSTGRES_URL to a disposable "
            "server (CI runs this against a postgres:16 service)"
        )

    from sqlalchemy import create_engine, inspect, text

    from app.workflows.models import WorkflowTaskRecord

    # The gate contract is an EMPTY database: drop both tables first so a
    # reused server (and earlier tests in this suite) cannot leak state.
    reset = create_engine(url)
    try:
        with reset.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS workflow_tasks"))
            connection.execute(text("DROP TABLE IF EXISTS workflows_alembic_version"))
    finally:
        reset.dispose()

    upgrade = _run_alembic(url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            version_rows = connection.execute(
                text("select version_num from workflows_alembic_version")
            ).fetchall()
            assert len(version_rows) == 1
            migrated = {column["name"] for column in inspect(engine).get_columns("workflow_tasks")}
        expected = {column.name for column in WorkflowTaskRecord.__table__.columns}
        assert migrated == expected
        downgrade = _run_alembic(url, "downgrade", "-1")
        assert downgrade.returncode == 0, downgrade.stderr
        with engine.connect() as connection:
            names = set(inspect(engine).get_table_names())
        assert "workflow_tasks" not in names
    finally:
        engine.dispose()
        cleanup = _run_alembic(url, "upgrade", "head")
        assert cleanup.returncode == 0, cleanup.stderr
