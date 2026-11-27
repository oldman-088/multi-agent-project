"""Alembic environment. Works on SQLite (default) and PostgreSQL (supported).

The URL comes from ``NEXUS_DATABASE_URL`` so credentials never sit in a checked-in
file. Every migration must apply on an empty SQLite database *and* an empty
PostgreSQL database (SPEC §9 migrations gate).
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Make the repository root importable when Alembic is invoked from anywhere.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Importing the models package registers every table on Base.metadata.
from app import models as _models  # noqa: E402,F401
from app.db.base import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    # ``disable_existing_loggers=False`` keeps application loggers alive.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    """Read the URL from the environment, coercing to the async driver."""
    url = os.environ.get("NEXUS_DATABASE_URL", "")
    if not url:
        url = "sqlite+aiosqlite:///./nexus.db"
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("sqlite://"):
        url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    elif url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    return url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a database connection."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # Batch mode makes SQLite ALTERs work; on PostgreSQL it is a no-op pass-through.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
