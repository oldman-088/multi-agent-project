"""Shared pytest fixtures: isolated app, database and clients.

The schema is created once per session from the model metadata (Alembic is tested
separately in ``test_migrations.py``) and every table is emptied between tests so
each test starts from a known state.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

os.environ.setdefault("NEXUS_ENV", "test")

from backend.app.core.config import Settings  # noqa: E402
from backend.app.db.base import Base  # noqa: E402
from backend.app.db.session import create_engine  # noqa: E402
from backend.app.main import create_app  # noqa: E402

TEST_JWT_SECRET = "test-jwt-secret-do-not-use-in-production-0123456789"
TEST_PASSWORD = "owner-password-123"
VIEWER_PASSWORD = "viewer-password-123"
SECOND_PASSWORD = "second-password-123"


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        env="test",
        jwt_secret=TEST_JWT_SECRET,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'nexus-test.db'}",
        access_token_ttl_seconds=900,
        refresh_token_ttl_seconds=3600,
        encryption_key=None,
        bridge_allowed_origins=["http://127.0.0.1:5173"],
    )


@pytest.fixture(scope="session")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    return make_settings(tmp_path_factory.mktemp("db"))


@pytest_asyncio.fixture(scope="session")
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    # Build the engine through the app factory so SQLite WAL/foreign-key pragmas
    # are installed exactly as in production.
    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def app(settings: Settings, engine: AsyncEngine) -> AsyncIterator[Any]:
    application = create_app(settings)
    # Share the session-scoped engine so the schema survives between tests.
    application.state.engine = engine
    application.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield application


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(engine: AsyncEngine) -> AsyncIterator[None]:
    """Empty every table before each test (child tables first)."""
    async with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            # Table names come from our own metadata, never from input.
            await connection.execute(text(f"DELETE FROM {table.name}"))  # noqa: S608
    yield


@pytest_asyncio.fixture
async def client(app: Any) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


@pytest_asyncio.fixture
async def session_factory(app: Any) -> async_sessionmaker[AsyncSession]:
    return app.state.session_factory


@pytest_asyncio.fixture
async def owner(client: AsyncClient) -> dict[str, Any]:
    """Run first-run setup and return tokens plus the created ids."""
    response = await client.post(
        "/api/auth/setup",
        json={
            "email": "owner@nexus.app",
            "password": TEST_PASSWORD,
            "display_name": "Owner",
            "organization_name": "Studio",
            "locale": "ar",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    payload["headers"] = {"Authorization": f"Bearer {payload['access_token']}"}
    me = await client.get("/api/auth/me", headers=payload["headers"])
    assert me.status_code == 200, me.text
    payload["me"] = me.json()
    payload["organization_id"] = me.json()["organization"]["id"]
    payload["user_id"] = me.json()["user"]["id"]
    return payload


@pytest_asyncio.fixture
async def viewer(client: AsyncClient, owner: dict[str, Any]) -> dict[str, Any]:
    """A second member of the same organization with the read-only viewer role."""
    response = await client.post(
        "/api/members",
        headers=owner["headers"],
        json={
            "email": "viewer@nexus.app",
            "display_name": "Viewer",
            "password": VIEWER_PASSWORD,
            "role": "viewer",
        },
    )
    assert response.status_code == 201, response.text
    login = await client.post(
        "/api/auth/login", json={"email": "viewer@nexus.app", "password": VIEWER_PASSWORD}
    )
    assert login.status_code == 200, login.text
    payload = login.json()
    payload["headers"] = {"Authorization": f"Bearer {payload['access_token']}"}
    return payload


@pytest_asyncio.fixture
async def agent(client: AsyncClient, owner: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(
        "/api/agents",
        headers=owner["headers"],
        json={
            "name": "Backend Engineer",
            "role": "backend",
            "goal": "Ship the API",
            "instructions": "Follow docs/SPEC.md",
            "tools": ["calc.evaluate", "time.now"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest_asyncio.fixture
async def second_tenant(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> dict[str, Any]:
    """Create a real second user + organization + owner token for isolation tests."""
    from backend.app.core.security import create_token, hash_password
    from backend.app.models.enums import OrgRole
    from backend.app.models.identity import Organization, OrganizationMember, User

    async with session_factory() as session:
        user = User(
            email="other-owner@other.example",
            display_name="Other Owner",
            password_hash=hash_password(SECOND_PASSWORD),
        )
        organization = Organization(name="Other Studio", slug="other-studio", autonomy_level="3")
        session.add_all([user, organization])
        await session.flush()
        session.add(
            OrganizationMember(organization_id=organization.id, user_id=user.id, role=OrgRole.OWNER)
        )
        await session.commit()
        token = create_token(
            subject=user.id,
            token_type="access",
            secret=TEST_JWT_SECRET,
            ttl_seconds=900,
            extra_claims={"org": organization.id, "role": "owner"},
        )
    return {
        "headers": {"Authorization": f"Bearer {token}"},
        "organization_id": organization.id,
        "user_id": user.id,
    }
