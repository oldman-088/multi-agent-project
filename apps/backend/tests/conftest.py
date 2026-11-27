"""Shared fixtures for the orchestration-slice test suite."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.workflows.models import Base


@pytest.fixture()
def session_factory(tmp_path: Path) -> Iterator[Callable[[], Session]]:
    """Session factory bound to a fresh database.

    Uses PostgreSQL when ``NEXUS_TEST_POSTGRES_URL`` points at a disposable
    server (CI sets it against a postgres:16 service), otherwise a fresh
    on-disk SQLite file per test.
    """
    pg_url = os.environ.get("NEXUS_TEST_POSTGRES_URL")
    if pg_url:
        engine = create_engine(pg_url)
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        try:
            yield sessionmaker(bind=engine, expire_on_commit=False)
        finally:
            # Leave the table in place: dropping it here would leave the
            # alembic version table claiming the revision is applied, and the
            # migration round-trip gate would then fail on the reused server.
            engine.dispose()
        return
    engine = create_engine(f"sqlite:///{tmp_path / 'workflows.db'}", connect_args={"timeout": 30})
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()
