"""Async engine/session plumbing and the Alembic migration runner.

docs/SPEC.md §4.3: the database (runs + events tables) is the single source of
truth; the events table is the execution history written with the outbox
pattern. SQLite (WAL-friendly, aiosqlite) is the local-first default.

Migrations are Alembic-managed. ``run_migrations`` is called from the app
lifespan (and from the test fixtures), so a freshly started backend always
brings its database up to ``head`` before serving traffic. CI additionally
runs ``alembic upgrade head`` explicitly, which is idempotent.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parents[2]


def to_sync_url(database_url: str) -> str:
    """Return a sync-driver URL for Alembic from the app's async URL.

    ``sqlite+aiosqlite://`` becomes ``sqlite://`` (stdlib sqlite3, which the
    Alembic CLI uses). PostgreSQL async URLs are passed through unchanged;
    PostgreSQL migration parity is documented as an untested gap.
    """
    if database_url.startswith("sqlite+aiosqlite://"):
        return database_url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    return database_url


def make_engine(database_url: str) -> AsyncEngine:
    connect_args: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        # Generous busy timeout so concurrent writers queue instead of
        # failing with "database is locked" (tests exercise concurrency).
        connect_args["timeout"] = 30.0
    engine = create_async_engine(database_url, connect_args=connect_args, future=True)
    if database_url.startswith("sqlite"):
        _install_sqlite_concurrency(engine)
    return engine


def _install_sqlite_concurrency(engine: AsyncEngine) -> None:
    """SQLite concurrency hardening for the local-first default (§4.2).

    - WAL journal: writers no longer block readers (the mode persists in the
      database file).
    - ``busy_timeout``: writer-vs-writer contention waits instead of failing.
    - ``BEGIN IMMEDIATE`` on every transaction: eliminates the read→write
      lock-upgrade deadlock that otherwise surfaces as an instant
      "database is locked" when concurrent requests first read and then
      write in the same transaction. Writer-writer conflicts then queue on
      the busy handler, and the per-run ``(run_id, sequence)`` unique
      constraint remains the backstop for sequence monotonicity.
    """

    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_connect(dbapi_connection: Any, _connection_record: Any) -> None:
        # Disable the driver's implicit BEGIN handling; SQLAlchemy emits
        # BEGIN IMMEDIATE itself via the begin event below.
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    @event.listens_for(engine.sync_engine, "begin")
    def _sqlite_begin(conn: Any) -> None:
        conn.exec_driver_sql("BEGIN IMMEDIATE")


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, future=True)


def run_migrations(database_url: str) -> None:
    """Bring the database to Alembic ``head`` (blocking; call via to_thread).

    The URL is passed explicitly through ``config.attributes`` (and mirrored
    into ``sqlalchemy.url``) so a ``NEXUS_DATABASE_URL`` value in the
    environment — meant for the alembic CLI — can never redirect this
    programmatic migration to a different database (that exact bug is what
    the conformance suite caught when running under scripts/check.sh).
    """
    ini_path = _BACKEND_DIR / "alembic.ini"
    if not ini_path.exists():
        # Non-editable install without the repo tree: fall back to creating
        # the schema directly from the models metadata.
        _create_all_fallback(database_url)
        return
    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    sync_url = to_sync_url(database_url)
    alembic_cfg.set_main_option("sqlalchemy.url", sync_url)
    alembic_cfg.attributes["configure_url"] = sync_url
    command.upgrade(alembic_cfg, "head")


def _create_all_fallback(database_url: str) -> None:
    from sqlalchemy import create_engine

    from backend.app.models import Base

    engine = create_engine(to_sync_url(database_url))
    try:
        Base.metadata.create_all(bind=engine)
    finally:
        engine.dispose()


async def run_migrations_async(database_url: str) -> None:
    await asyncio.to_thread(run_migrations, database_url)


async def ping_database(session: AsyncSession) -> bool:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


__all__ = [
    "make_engine",
    "make_sessionmaker",
    "ping_database",
    "run_migrations",
    "run_migrations_async",
    "to_sync_url",
]
