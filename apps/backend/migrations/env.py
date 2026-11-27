"""Alembic environment for the orchestration slice (workflow-engine tables).

The URL comes from the environment so no credentials sit in a checked-in file:
``WORKFLOWS_DATABASE_URL`` wins, then ``NEXUS_DATABASE_URL``, then
``DATABASE_URL``, then a local SQLite file.  Async driver URLs are coerced to
their sync equivalents because this chain runs on a sync engine.

This chain keeps its schema version in ``workflows_alembic_version`` (not the
default ``alembic_version``) so it can share one database with the backend
slice's migration chain without either chain re-reading the other's revisions.

Migrations must apply on an empty SQLite database *and* an empty PostgreSQL
database (docs/SPEC.md §9).
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.workflows.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

VERSION_TABLE = "workflows_alembic_version"


def _database_url() -> str:
    url = (
        os.environ.get("WORKFLOWS_DATABASE_URL")
        or os.environ.get("NEXUS_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or "sqlite:///./workflows.db"
    )
    # This chain is synchronous: coerce async drivers to their sync twins.
    url = url.replace("sqlite+aiosqlite://", "sqlite://")
    url = url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DBAPI connection)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        url=_database_url(),
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
