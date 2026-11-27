"""Async engine/session factory plus SQLite WAL configuration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Request
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.app.core.config import Settings, get_settings
from backend.app.db.base import Base


def _normalise_url(url: str) -> str:
    """Accept ``postgresql://`` and coerce it to the async driver."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def create_engine(settings: Settings | None = None) -> AsyncEngine:
    settings = settings or get_settings()
    url = _normalise_url(settings.database_url)
    kwargs: dict[str, object] = {"echo": settings.db_echo, "future": True}
    if url.startswith("sqlite"):
        # check_same_thread=False is required for the sync driver inside async tests.
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 10
    engine = create_async_engine(url, **kwargs)
    if url.startswith("sqlite"):
        _install_sqlite_pragmas(engine)
    return engine


def _install_sqlite_pragmas(engine: AsyncEngine) -> None:
    """WAL mode, foreign keys ON and a busy timeout (SPEC §4.2)."""

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def create_all(engine: AsyncEngine) -> None:
    """Create the schema directly from metadata (tests/quick start only).

    Production and CI migrations go through Alembic; this helper exists so tests
    can build a schema without shelling out.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@asynccontextmanager
async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """Transactional scope: commit on success, roll back on error."""
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def healthcheck(engine: AsyncEngine) -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # pragma: no cover - defensive
        return False


# --------------------------------------------------------------------------- #
# FastAPI dependency
# --------------------------------------------------------------------------- #
# The engine and session factory are created once at app startup and stored on
# ``app.state``; this dependency reads them so tests can swap the database.
async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a session bound to the application's engine.

    The factory lives on ``app.state.session_factory`` (set in the app factory and
    in tests), which keeps every request in one place and avoids globals.
    """
    factory = getattr(getattr(request, "app", None), "state", None)
    factory = getattr(factory, "session_factory", None)
    if factory is None:  # pragma: no cover - misconfiguration guard
        raise RuntimeError("session_factory is not configured on the application")
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
