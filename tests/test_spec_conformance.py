"""Spec-conformance tests for ``docs/SPEC.md`` (AATM-7a3d63bb).

Everything here runs without an external service: the real FastAPI app, the real
service layer and a real SQLite database (WAL mode) inside the test process.

Coverage map
------------
* §7 (Event schema) — ``sequence`` is monotonic per run; contiguous from 1; a
  duplicate ``(run_id, sequence)`` is rejected by the database; the replay cursor
  (``after_sequence``) never repeats or skips; run-less organisation events are
  monotonic too; payloads are secret-redacted before they are stored.
* §6 Phase 2.1 / §3.2 — RBAC: 401 without credentials, 403 for a role that lacks
  the permission, and tenant isolation: a user of organisation **A** can never
  read organisation **B**'s agents, runs, events, approvals, audit rows or tools.
* §3.2 / §13.2 (Tool Gateway + action policy) — ``allow`` executes, ``ask``
  creates a pending approval instead of running, ``deny`` blocks execution; the
  first matching rule wins; argument schemas and the agent tool allow-list are
  enforced; every decision is audited, including denials.
* §3.2 / §13.4 (kill switch) — the global emergency stop blocks new work until it
  is cleared, is persisted (survives a fresh app instance restart), needs
  ``system:write``, is idempotent, and emits exactly one event per transition.

Mocks
-----
``MockModelConnection`` and ``MockBrowserSession`` stand in for the external
connections of SPEC §4.4. They are *inputs* only: they hand the backend the same
data a real connection would, and every assertion is made against the real
application, services and database. No backend behaviour is reimplemented here.

Running
-------
The suite is self-contained (its own fixtures) so it can run on a checkout that
carries only this file. ``NEXUS_BACKEND_ROOT`` may point at a worktree containing
``backend/``; otherwise the backend is imported from the repository root. When
the backend package is not present the module skips with an explicit, recorded
reason (SPEC §9) — never a silent pass. ``NEXUS_BASE_URL`` additionally enables a
read-only smoke test against a live server.

Gaps that need services this suite cannot start (browser bridge, workers,
PostgreSQL) are recorded in ``docs/SPEC_CONFORMANCE.md`` and in the PR body.
"""

from __future__ import annotations

import importlib.util
import os
import secrets
import sys
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------- #
# Import the backend. An explicit NEXUS_BACKEND_ROOT wins over the repo root so
# this file can be verified against a worktree that is not the checked-out tree.
# --------------------------------------------------------------------------- #
_backend_root = os.environ.get("NEXUS_BACKEND_ROOT")
for _candidate in (REPO_ROOT, Path(_backend_root).expanduser() if _backend_root else None):
    if _candidate is not None and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

if importlib.util.find_spec("pytest_asyncio") is None:  # pragma: no cover - env guard
    pytest.skip(
        "pytest-asyncio is required for the async conformance tests; install the test "
        "extra (pip install -e '.[test]'). Recorded skip, not a pass (SPEC §9).",
        allow_module_level=True,
    )

if importlib.util.find_spec("backend") is None:  # pragma: no cover - env guard
    pytest.skip(
        "The NEXUS backend package (backend/) is not present in this checkout, so the "
        "docs/SPEC.md conformance suite cannot run. It arrives with the backend pull "
        "request; set NEXUS_BACKEND_ROOT to a worktree that contains backend/ to run it "
        "now. This is a recorded skip, never a silent pass (SPEC §9).",
        allow_module_level=True,
    )

import pytest_asyncio  # noqa: E402
from backend.app.core.config import Settings  # noqa: E402
from backend.app.core.security import create_token, hash_password, new_id  # noqa: E402
from backend.app.db.base import Base  # noqa: E402
from backend.app.db.session import create_engine  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models.enums import OrgRole  # noqa: E402
from backend.app.models.identity import Organization, OrganizationMember, User  # noqa: E402
from backend.app.models.runs import Event, ToolDefinition  # noqa: E402
from backend.app.services import event_service  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker  # noqa: E402

#: Generated per run, so the test file never carries a credential-like literal.
JWT_SECRET = secrets.token_urlsafe(48)
TEST_PASSWORD = secrets.token_urlsafe(18)
VIEWER_PASSWORD = secrets.token_urlsafe(18)
SECOND_PASSWORD = secrets.token_urlsafe(18)
REDACTED = "***redacted***"

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- #
# Fixtures: one isolated database, app and client per test (function scoped, so
# no event loop or pool is ever shared between tests).
# --------------------------------------------------------------------------- #
@pytest.fixture
def spec_settings(tmp_path: Path) -> Settings:
    return Settings(
        env="test",
        jwt_secret=JWT_SECRET,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'spec-conformance.db'}",
        access_token_ttl_seconds=900,
        refresh_token_ttl_seconds=3600,
        encryption_key=None,
        bridge_allowed_origins=["http://127.0.0.1:5173"],
    )


@pytest_asyncio.fixture
async def spec_engine(spec_settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(spec_settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


def _bind(app: Any, engine: AsyncEngine) -> Any:
    """Point the app at the test engine (as the backend's own conftest does)."""
    app.state.engine = engine
    app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return app


@pytest_asyncio.fixture
async def spec_app(spec_settings: Settings, spec_engine: AsyncEngine) -> Any:
    return _bind(create_app(spec_settings), spec_engine)


@pytest_asyncio.fixture
async def spec_client(spec_app: Any) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=spec_app)
    async with AsyncClient(transport=transport, base_url="http://spec.test") as client:
        yield client


@pytest_asyncio.fixture
async def spec_session_factory(spec_app: Any) -> async_sessionmaker[AsyncSession]:
    return spec_app.state.session_factory


@pytest_asyncio.fixture
async def tenant_a(spec_client: AsyncClient) -> dict[str, Any]:
    """First-run setup: owner of organisation A (autonomy level 3 by default)."""
    response = await spec_client.post(
        "/api/auth/setup",
        json={
            "email": "owner-a@spec.example",
            "password": TEST_PASSWORD,
            "display_name": "Owner A",
            "organization_name": "Organisation A",
            "locale": "ar",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    payload["headers"] = {"Authorization": f"Bearer {payload['access_token']}"}
    me = await spec_client.get("/api/auth/me", headers=payload["headers"])
    assert me.status_code == 200, me.text
    payload["organization_id"] = me.json()["organization"]["id"]
    payload["user_id"] = me.json()["user"]["id"]
    return payload


@pytest_asyncio.fixture
async def viewer_a(spec_client: AsyncClient, tenant_a: dict[str, Any]) -> dict[str, Any]:
    """A second member of organisation A holding the read-only ``viewer`` role."""
    added = await spec_client.post(
        "/api/members",
        headers=tenant_a["headers"],
        json={
            "email": "viewer-a@spec.example",
            "display_name": "Viewer A",
            "password": VIEWER_PASSWORD,
            "role": "viewer",
        },
    )
    assert added.status_code == 201, added.text
    login = await spec_client.post(
        "/api/auth/login", json={"email": "viewer-a@spec.example", "password": VIEWER_PASSWORD}
    )
    assert login.status_code == 200, login.text
    payload = login.json()
    payload["headers"] = {"Authorization": f"Bearer {payload['access_token']}"}
    return payload


@pytest_asyncio.fixture
async def tenant_b(
    spec_client: AsyncClient, spec_session_factory: async_sessionmaker[AsyncSession]
) -> dict[str, Any]:
    """A real second user + organisation with its own owner token (tenant B)."""
    async with spec_session_factory() as session:
        user = User(
            email="owner-b@spec.example",
            display_name="Owner B",
            password_hash=hash_password(SECOND_PASSWORD),
        )
        organization = Organization(
            name="Organisation B", slug="organisation-b", autonomy_level="3"
        )
        session.add_all([user, organization])
        await session.flush()
        session.add(
            OrganizationMember(organization_id=organization.id, user_id=user.id, role=OrgRole.OWNER)
        )
        await session.commit()
        token = create_token(
            subject=user.id,
            token_type="access",
            secret=JWT_SECRET,
            ttl_seconds=900,
            extra_claims={"org": organization.id, "role": "owner"},
        )
    return {
        "headers": {"Authorization": f"Bearer {token}"},
        "organization_id": organization.id,
        "user_id": user.id,
    }


@pytest_asyncio.fixture
async def agent_a(spec_client: AsyncClient, tenant_a: dict[str, Any]) -> dict[str, Any]:
    response = await spec_client.post(
        "/api/agents",
        headers=tenant_a["headers"],
        json={
            "name": "Conformance Engineer",
            "role": "backend",
            "goal": "Prove the spec holds",
            "instructions": "Follow docs/SPEC.md",
            "tools": ["calc.evaluate", "time.now"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# Mocks for the external connections of SPEC §4.4.
# --------------------------------------------------------------------------- #
@dataclass
class MockModelConnection:
    """In-memory stand-in for a model connection.

    It reports honest capabilities (SPEC §3.3: no invented usage) and replay-writes
    a scripted agent turn through the **real** event service, which is exactly the
    input a real connection would produce.
    """

    name: str = "mock-model"
    capabilities: dict[str, str] = field(
        default_factory=lambda: {"streaming": "supported", "usage_reporting": "unsupported"}
    )

    def scripted_turn(self) -> list[tuple[str, dict[str, Any]]]:
        return [
            ("agent.started", {"step": 1, "connection": self.name}),
            ("agent.message", {"content": "planning the work", "usage": None}),
            (
                "tool.execution.started",
                {"tool": "calc.evaluate", "arguments": {"expression": "2+2"}},
            ),
            ("tool.execution.completed", {"tool": "calc.evaluate", "result": {"value": 4}}),
            ("agent.completed", {"steps": 1, "access_token": "must-not-be-stored"}),
        ]

    async def run_turn(
        self,
        session: AsyncSession,
        *,
        organization_id: str,
        run_id: str,
        agent_id: str,
    ) -> list[Event]:
        """Persist the scripted turn and return the stored events, in order."""
        events: list[Event] = []
        for event_type, payload in self.scripted_turn():
            events.append(
                await event_service.append_event(
                    session,
                    organization_id=organization_id,
                    run_id=run_id,
                    agent_id=agent_id,
                    event_type=event_type,
                    payload=payload,
                )
            )
        await session.commit()
        return events


@dataclass
class MockBrowserSession:
    """In-memory stand-in for a browser tab driven through the real service layer.

    ``transition`` calls ``connection_service.update_tab`` so the side effects
    (state change, ``browser.*`` event, audit row) are the production ones.
    """

    label: str = "Mock tab"
    device_credential: str = field(default_factory=lambda: secrets.token_urlsafe(24))

    async def open_tab(
        self, client: AsyncClient, headers: dict[str, str], *, provider_slug: str = "mock"
    ) -> dict[str, Any]:
        paired = await client.post(
            "/api/devices/pair",
            headers=headers,
            json={"label": self.label, "userscript_version": "1.0.0"},
        )
        assert paired.status_code == 201, paired.text
        tab = await client.post(
            f"/api/devices/{paired.json()['device_id']}/tabs",
            headers=headers,
            params={"provider_slug": provider_slug, "url": "https://mock.local/chat"},
        )
        assert tab.status_code == 201, tab.text
        return tab.json()

    async def transition(
        self, client: AsyncClient, headers: dict[str, str], tab_id: str, state: str
    ) -> dict[str, Any]:
        updated = await client.patch(
            f"/api/browser-sessions/{tab_id}", headers=headers, json={"state": state}
        )
        assert updated.status_code == 200, updated.text
        return updated.json()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
async def _create_run(
    client: AsyncClient, headers: dict[str, str], agent_id: str, directive: str = "conformance"
) -> dict[str, Any]:
    response = await client.post(
        "/api/runs", headers=headers, json={"agent_id": agent_id, "directive": directive}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _run_events(
    client: AsyncClient, headers: dict[str, str], run_id: str, **params: Any
) -> list[dict[str, Any]]:
    response = await client.get(f"/api/runs/{run_id}/events", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _sequences(events: Iterable[dict[str, Any]]) -> list[int]:
    return [event["sequence"] for event in events]


async def _sync_tools(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.post("/api/tools/sync-builtin", headers=headers)
    assert response.status_code == 200, response.text
    return {tool["slug"]: tool for tool in response.json()}


async def _invoke(
    client: AsyncClient, headers: dict[str, str], slug: str, arguments: dict[str, Any], **extra: Any
) -> Any:
    return await client.post(
        "/api/tools/invoke",
        headers=headers,
        json={"tool_slug": slug, "arguments": arguments, **extra},
    )


async def _audit(client: AsyncClient, headers: dict[str, str], action: str) -> list[dict]:
    response = await client.get("/api/audit", headers=headers, params={"action": action})
    assert response.status_code == 200, response.text
    return response.json()


# =========================================================================== #
# §7 — event sequencing is monotonic per run
# =========================================================================== #
async def test_run_events_are_monotonic_and_contiguous(
    spec_client: AsyncClient, tenant_a: dict[str, Any], agent_a: dict[str, Any]
) -> None:
    """A run's events form a gapless, strictly increasing sequence from 1."""
    headers = tenant_a["headers"]
    run = await _create_run(spec_client, headers, agent_a["id"])

    for action in ("start", "pause", "resume", "complete"):
        response = await spec_client.post(f"/api/runs/{run['id']}/{action}", headers=headers)
        assert response.status_code == 200, f"{action}: {response.text}"

    events = await _run_events(spec_client, headers, run["id"])
    sequences = _sequences(events)
    # Gapless, strictly increasing, starting at 1 — the per-run contract of §7.
    assert sequences == list(range(1, len(events) + 1)), sequences
    assert len(set(sequences)) == len(sequences), "sequence must never repeat inside a run"

    # The lifecycle transitions are present and in the order they happened.
    types = [event["event_type"] for event in events]
    expected_order = ["run.created", "run.started", "run.paused", "run.resumed", "run.completed"]
    positions = [types.index(name) for name in expected_order]
    assert positions == sorted(positions), types
    assert types[0] == "run.created"
    assert types[-1] == "run.completed"

    # The run row agrees with its event log (the log is the source of truth, §4.3).
    detail = await spec_client.get(f"/api/runs/{run['id']}", headers=headers)
    assert detail.json()["last_sequence"] == sequences[-1]

    # Replay cursor: after_sequence=N returns exactly the events after N.
    cursor = sequences[len(sequences) // 2]
    replay = await _run_events(spec_client, headers, run["id"], after_sequence=cursor)
    assert _sequences(replay) == [seq for seq in sequences if seq > cursor]
    assert all(event["sequence"] > cursor for event in replay)


async def test_each_run_has_its_own_sequence_counter(
    spec_client: AsyncClient,
    tenant_a: dict[str, Any],
    agent_a: dict[str, Any],
    spec_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Interleaved runs each keep a private 1..n sequence (SPEC §7: per run)."""
    headers = tenant_a["headers"]
    run_a = await _create_run(spec_client, headers, agent_a["id"], "run A")
    run_b = await _create_run(spec_client, headers, agent_a["id"], "run B")

    mock = MockModelConnection()
    async with spec_session_factory() as session:
        await mock.run_turn(
            session,
            organization_id=tenant_a["organization_id"],
            run_id=run_b["id"],
            agent_id=agent_a["id"],
        )

    await spec_client.post(f"/api/runs/{run_a['id']}/start", headers=headers)
    async with spec_session_factory() as session:
        await event_service.append_event(
            session,
            organization_id=tenant_a["organization_id"],
            run_id=run_b["id"],
            agent_id=agent_a["id"],
            event_type="provider.response.received",
            payload={"model": "mock"},
        )
        await session.commit()
    await spec_client.post(f"/api/runs/{run_a['id']}/complete", headers=headers)

    events_a = await _run_events(spec_client, headers, run_a["id"])
    events_b = await _run_events(spec_client, headers, run_b["id"])

    assert _sequences(events_a) == [1, 2, 3]
    # run.created + the five mock-turn events + provider.response.received.
    assert _sequences(events_b) == [1, 2, 3, 4, 5, 6, 7]
    assert {event["run_id"] for event in events_a} == {run_a["id"]}
    assert {event["run_id"] for event in events_b} == {run_b["id"]}


async def test_duplicate_sequence_is_rejected_by_the_database(
    spec_client: AsyncClient,
    tenant_a: dict[str, Any],
    agent_a: dict[str, Any],
    spec_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``uq_events_run_sequence`` makes a re-used sequence impossible, not just unlikely."""
    run = await _create_run(spec_client, tenant_a["headers"], agent_a["id"])

    async with spec_session_factory() as session:
        with pytest.raises(IntegrityError):
            await event_service.append_event(
                session,
                organization_id=tenant_a["organization_id"],
                run_id=run["id"],
                event_type="agent.message",
                payload={"content": "duplicate"},
                sequence=1,  # already used by run.created
            )
            await session.commit()
        await session.rollback()

    events = await _run_events(spec_client, tenant_a["headers"], run["id"])
    assert _sequences(events) == [1]


async def test_mock_connection_turn_is_persisted_in_order_and_redacted(
    spec_client: AsyncClient,
    tenant_a: dict[str, Any],
    agent_a: dict[str, Any],
    spec_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A connection's scripted turn lands in order and secrets never reach the log."""
    mock = MockModelConnection()
    assert mock.capabilities["usage_reporting"] == "unsupported"  # honest, §3.3
    run = await _create_run(spec_client, tenant_a["headers"], agent_a["id"])

    async with spec_session_factory() as session:
        stored = await mock.run_turn(
            session,
            organization_id=tenant_a["organization_id"],
            run_id=run["id"],
            agent_id=agent_a["id"],
        )

    assert [event.sequence for event in stored] == [2, 3, 4, 5, 6]
    events = await _run_events(spec_client, tenant_a["headers"], run["id"])
    assert [event["event_type"] for event in events] == [
        "run.created",
        *[name for name, _ in mock.scripted_turn()],
    ]
    # §7: payloads are secret-redacted before they are stored.
    assert events[-1]["payload"]["access_token"] == REDACTED
    assert events[0]["payload"]["directive_length"] == len("conformance")


async def test_organization_stream_is_monotonic_and_resumable(
    spec_client: AsyncClient, tenant_a: dict[str, Any]
) -> None:
    """Run-less organisation events keep their own monotonic sequence (§7)."""
    headers = tenant_a["headers"]
    tab = await MockBrowserSession().open_tab(spec_client, headers)
    await MockBrowserSession().transition(spec_client, headers, tab["id"], "WAITING_FOR_USER")
    await MockBrowserSession().transition(spec_client, headers, tab["id"], "READY")

    events = await spec_client.get("/api/events", headers=headers)
    assert events.status_code == 200, events.text
    run_less = [event for event in events.json() if event["run_id"] is None]
    sequences = _sequences(run_less)
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
    assert "browser.waiting_for_user" in {event["event_type"] for event in run_less}

    cursor = sequences[0]
    resumed = await spec_client.get(
        "/api/events", headers=headers, params={"after_sequence": cursor}
    )
    assert all(event["sequence"] > cursor for event in resumed.json())


# =========================================================================== #
# §6 Phase 2.1 / §3.2 — authentication, RBAC and tenant isolation
# =========================================================================== #
CONFORMANCE_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/auth/me"),
    ("GET", "/api/agents"),
    ("POST", "/api/agents"),
    ("GET", "/api/runs"),
    ("POST", "/api/runs"),
    ("GET", "/api/events"),
    ("GET", "/api/approvals"),
    ("GET", "/api/tools"),
    ("POST", "/api/tools/invoke"),
    ("GET", "/api/audit"),
    ("GET", "/api/system/autonomy"),
    ("PUT", "/api/system/autonomy"),
    ("POST", "/api/system/action-policy/evaluate"),
    ("POST", "/api/kill-switch"),
    ("GET", "/api/kill-switch"),
]


@pytest.mark.parametrize(("method", "path"), CONFORMANCE_ROUTES)
async def test_anonymous_callers_get_401(
    spec_client: AsyncClient, tenant_a: dict[str, Any], method: str, path: str
) -> None:
    """Authentication is required everywhere except the documented public routes."""
    response = await spec_client.request(method, path, json={})
    assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
    assert response.json()["error"]["code"] in {
        "unauthenticated",
        "token_expired",
        "invalid_token",
        "wrong_token_type",
    }


async def test_viewer_reads_but_cannot_write(
    spec_client: AsyncClient, tenant_a: dict[str, Any], viewer_a: dict[str, Any]
) -> None:
    """RBAC: ``viewer`` holds read grants only (SPEC §6 Phase 2.1)."""
    headers = viewer_a["headers"]

    # Reads the viewer is granted.
    for path in (
        "/api/agents",
        "/api/runs",
        "/api/events",
        "/api/approvals",
        "/api/tools",
        "/api/audit",
        "/api/system/autonomy",
        "/api/system/action-policy",
    ):
        assert (await spec_client.get(path, headers=headers)).status_code == 200, path

    # Writes the viewer is not granted → 403 with the shared error envelope.
    for method, path, body in (
        ("POST", "/api/agents", {"name": "Nope", "role": "backend"}),
        ("PUT", "/api/system/autonomy", {"level": "3"}),
        ("PUT", "/api/system/action-policy", [{"decision": "allow", "match_all": True}]),
        ("POST", "/api/kill-switch", {"engage": True, "reason": "not allowed"}),
        ("POST", "/api/tools/sync-builtin", None),
    ):
        response = await spec_client.request(method, path, headers=headers, json=body)
        assert response.status_code == 403, (
            f"{method} {path} -> {response.status_code} {response.text}"
        )
        assert response.json()["error"]["code"] == "forbidden"

    # The same writes succeed for the owner: the 403 is about the role, not the route.
    assert (
        await spec_client.put(
            "/api/system/autonomy", headers=tenant_a["headers"], json={"level": "3"}
        )
    ).status_code == 200


async def test_organisation_b_cannot_read_organisation_a_resources(
    spec_client: AsyncClient,
    tenant_a: dict[str, Any],
    tenant_b: dict[str, Any],
    agent_a: dict[str, Any],
) -> None:
    """Tenant isolation: org B sees none of org A's agents, runs or events."""
    headers_a, headers_b = tenant_a["headers"], tenant_b["headers"]
    run = await _create_run(spec_client, headers_a, agent_a["id"])

    assert (
        await spec_client.get(f"/api/agents/{agent_a['id']}", headers=headers_b)
    ).status_code == 404
    assert (await spec_client.get("/api/agents", headers=headers_b)).json()["total"] == 0
    assert (await spec_client.get(f"/api/runs/{run['id']}", headers=headers_b)).status_code == 404
    assert (await spec_client.get("/api/runs", headers=headers_b)).json()["total"] == 0
    assert (
        await spec_client.get(f"/api/runs/{run['id']}/events", headers=headers_b)
    ).status_code == 404
    assert (await spec_client.get("/api/events", headers=headers_b)).json() == []

    # The owner of A still sees everything: isolation, not breakage.
    assert (
        await spec_client.get(f"/api/agents/{agent_a['id']}", headers=headers_a)
    ).status_code == 200
    assert len(await _run_events(spec_client, headers_a, run["id"])) == 1


async def test_organisation_b_cannot_read_audit_tools_or_decide_approvals(
    spec_client: AsyncClient, tenant_a: dict[str, Any], tenant_b: dict[str, Any]
) -> None:
    """Audit rows, the tool registry and approvals are all scoped per organisation."""
    headers_a, headers_b = tenant_a["headers"], tenant_b["headers"]
    await _sync_tools(spec_client, headers_a)
    await spec_client.put("/api/system/autonomy", headers=headers_a, json={"level": "0"})
    invocation = await _invoke(spec_client, headers_a, "calc.evaluate", {"expression": "1+1"})
    assert invocation.status_code == 200, invocation.text
    approval_id = invocation.json()["approval_id"]
    assert approval_id

    # B sees no audit rows and an empty tool registry of its own…
    assert await _audit(spec_client, headers_b, "tools.invoke") == []
    assert (await spec_client.get("/api/tools", headers=headers_b)).json() == []
    # …and cannot invoke a tool that only A registered.
    cross = await _invoke(spec_client, headers_b, "calc.evaluate", {"expression": "1+1"})
    assert cross.status_code == 404, cross.text
    # …nor decide A's pending approval.
    decided = await spec_client.post(
        f"/api/approvals/{approval_id}/decide", headers=headers_b, json={"approve": True}
    )
    assert decided.status_code in {403, 404}, decided.text
    assert (await spec_client.get("/api/approvals", headers=headers_b)).json()["total"] == 0

    still_pending = await spec_client.get("/api/approvals", headers=headers_a)
    assert still_pending.json()["items"][0]["status"] == "pending"


async def test_cannot_select_an_organisation_you_do_not_belong_to(
    spec_client: AsyncClient, tenant_a: dict[str, Any], tenant_b: dict[str, Any]
) -> None:
    """The ``X-Organization-Id`` override must be a real membership (no header spoofing)."""
    spoofed = {**tenant_b["headers"], "X-Organization-Id": tenant_a["organization_id"]}
    response = await spec_client.get("/api/agents", headers=spoofed)
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "forbidden"

    honest = {**tenant_b["headers"], "X-Organization-Id": tenant_b["organization_id"]}
    assert (await spec_client.get("/api/agents", headers=honest)).status_code == 200


# =========================================================================== #
# §3.2 / §13.2 — Tool Gateway policy: allow / ask / deny
# =========================================================================== #
async def test_policy_allow_executes_the_tool_and_audits_it(
    spec_client: AsyncClient, tenant_a: dict[str, Any]
) -> None:
    headers = tenant_a["headers"]
    await _sync_tools(spec_client, headers)
    assert (await spec_client.get("/api/system/autonomy", headers=headers)).json()[
        "autonomy_level"
    ] == "3"

    response = await _invoke(spec_client, headers, "calc.evaluate", {"expression": "(2+3)*4"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"] == "allow"
    assert body["outcome"] == "success"
    assert body["result"] == {"value": 20}

    audit_rows = await _audit(spec_client, headers, "tools.invoke")
    assert len(audit_rows) == 1
    assert audit_rows[0]["outcome"] == "success"
    assert audit_rows[0]["context"]["decision"] == "allow"


async def test_policy_ask_creates_a_pending_approval_and_does_not_run(
    spec_client: AsyncClient, tenant_a: dict[str, Any]
) -> None:
    """Level 0 asks for every call (SPEC §13.1); the tool must not execute."""
    headers = tenant_a["headers"]
    await _sync_tools(spec_client, headers)
    updated = await spec_client.put("/api/system/autonomy", headers=headers, json={"level": "0"})
    assert updated.status_code == 200, updated.text

    response = await _invoke(spec_client, headers, "calc.evaluate", {"expression": "6*7"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"] == "ask"
    assert body["outcome"] == "awaiting_approval"
    assert body["result"] is None, "an ask must never return a computed result"
    assert body["approval_id"]

    approvals = await spec_client.get("/api/approvals", headers=headers)
    assert approvals.json()["total"] == 1
    assert approvals.json()["items"][0]["status"] == "pending"
    assert approvals.json()["items"][0]["tool_slug"] == "calc.evaluate"


async def test_irreversible_and_flagged_tools_always_ask(
    spec_client: AsyncClient,
    tenant_a: dict[str, Any],
    spec_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Full-auto still asks for irreversible actions and ``requires_approval`` tools."""
    headers = tenant_a["headers"]
    await _sync_tools(spec_client, headers)

    irreversible = await spec_client.post(
        "/api/system/action-policy/evaluate",
        headers=headers,
        json={"tool": "fs.delete_outside_workspace"},
    )
    assert irreversible.json()["decision"] == "ask"

    # A tool the owner flagged requires_approval is forced to ``ask`` even when
    # the policy would allow it (SPEC §6 Phase 2 item 7).
    async with spec_session_factory() as session:
        session.add(
            ToolDefinition(
                id=new_id("tol"),
                organization_id=tenant_a["organization_id"],
                slug="dangerous.deploy",
                display_name="Deploy",
                description="Flagged requires_approval for the conformance suite",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                requires_approval=True,
                enabled=True,
                category="builtin",
            )
        )
        await session.commit()

    response = await _invoke(spec_client, headers, "dangerous.deploy", {})
    assert response.status_code == 200, response.text
    assert response.json()["decision"] == "ask"
    assert response.json()["outcome"] == "awaiting_approval"
    assert response.json()["approval_id"]


async def test_policy_deny_blocks_execution_and_is_audited(
    spec_client: AsyncClient, tenant_a: dict[str, Any]
) -> None:
    headers = tenant_a["headers"]
    await _sync_tools(spec_client, headers)
    written = await spec_client.put(
        "/api/system/action-policy",
        headers=headers,
        json=[
            {"decision": "deny", "tool": "calc.evaluate"},
            {"decision": "allow", "match_all": True},
        ],
    )
    assert written.status_code == 200, written.text

    response = await _invoke(spec_client, headers, "calc.evaluate", {"expression": "1/0"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"] == "deny"
    assert body["outcome"] == "denied"
    assert body["result"] is None, "a denied call must never execute"
    assert "denied" in (body["error"] or "").lower()

    audit_rows = await _audit(spec_client, headers, "tools.invoke")
    assert len(audit_rows) == 1
    assert audit_rows[0]["outcome"] == "denied"
    assert audit_rows[0]["context"]["decision"] == "deny"


async def test_policy_first_match_wins(spec_client: AsyncClient, tenant_a: dict[str, Any]) -> None:
    """Ordered rules: the first matching rule decides (SPEC §13.2)."""
    headers = tenant_a["headers"]
    written = await spec_client.put(
        "/api/system/action-policy",
        headers=headers,
        json=[
            {"decision": "allow", "tool": "http.get"},
            {"decision": "deny", "tool": "http.*"},
            {"decision": "ask", "match_all": True},
        ],
    )
    assert written.status_code == 200, written.text

    allowed = await spec_client.post(
        "/api/system/action-policy/evaluate", headers=headers, json={"tool": "http.get"}
    )
    assert allowed.json() == {
        "decision": "allow",
        "matched_rule": 0,
        "reason": allowed.json()["reason"],
    }
    other_http = await spec_client.post(
        "/api/system/action-policy/evaluate", headers=headers, json={"tool": "http.post"}
    )
    assert other_http.json()["decision"] == "deny"
    assert other_http.json()["matched_rule"] == 1

    unrelated = await spec_client.post(
        "/api/system/action-policy/evaluate", headers=headers, json={"tool": "time.now"}
    )
    assert unrelated.json()["decision"] == "ask"
    assert unrelated.json()["matched_rule"] == 2


async def test_gateway_enforces_argument_schema_and_agent_allowlist(
    spec_client: AsyncClient, tenant_a: dict[str, Any], agent_a: dict[str, Any]
) -> None:
    """JSON Schema validation and the per-agent tool allow-list (SPEC §6 P2.7)."""
    headers = tenant_a["headers"]
    await _sync_tools(spec_client, headers)

    missing_arg = await _invoke(spec_client, headers, "calc.evaluate", {})
    assert missing_arg.status_code == 422, missing_arg.text
    assert missing_arg.json()["error"]["code"] == "invalid_tool_arguments"

    restricted = await _invoke(
        spec_client, headers, "http.get", {"url": "http://localhost/"}, agent_id=agent_a["id"]
    )
    assert restricted.status_code == 403, restricted.text
    assert restricted.json()["error"]["code"] == "tool_not_allowed"

    allowed = await _invoke(
        spec_client, headers, "calc.evaluate", {"expression": "7*6"}, agent_id=agent_a["id"]
    )
    assert allowed.status_code == 200
    assert allowed.json()["outcome"] == "success"


async def test_gateway_refuses_hosts_outside_the_allowlist(
    spec_client: AsyncClient, tenant_a: dict[str, Any]
) -> None:
    """``http.get`` stays offline and refuses non-allow-listed hosts (§3.1/§3.2)."""
    headers = tenant_a["headers"]
    await _sync_tools(spec_client, headers)

    blocked = await _invoke(spec_client, headers, "http.get", {"url": "https://example.com/x"})
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["error"]["code"] == "host_not_allowed"

    audit_rows = await _audit(spec_client, headers, "tools.invoke")
    assert any(row["outcome"] == "denied" for row in audit_rows)


async def test_every_gateway_decision_is_audited(
    spec_client: AsyncClient, tenant_a: dict[str, Any]
) -> None:
    """Allow, ask and deny all produce exactly one audit row each (§3.2)."""
    headers = tenant_a["headers"]
    await _sync_tools(spec_client, headers)

    assert (
        await _invoke(spec_client, headers, "calc.evaluate", {"expression": "1+1"})
    ).status_code == 200
    await spec_client.put("/api/system/autonomy", headers=headers, json={"level": "0"})
    ask = await _invoke(spec_client, headers, "time.now", {})
    assert ask.json()["decision"] == "ask"

    await spec_client.put(
        "/api/system/action-policy",
        headers=headers,
        json=[{"decision": "deny", "match_all": True}],
    )
    deny = await _invoke(spec_client, headers, "time.now", {})
    assert deny.json()["decision"] == "deny"

    decisions = [
        row["context"]["decision"] for row in await _audit(spec_client, headers, "tools.invoke")
    ]
    assert sorted(decisions) == ["allow", "ask", "deny"]


# =========================================================================== #
# §3.2 / §13.4 — the global kill switch
# =========================================================================== #
async def test_kill_switch_blocks_new_work_until_cleared(
    spec_client: AsyncClient, tenant_a: dict[str, Any], agent_a: dict[str, Any]
) -> None:
    headers = tenant_a["headers"]
    run = await _create_run(spec_client, headers, agent_a["id"])

    engaged = await spec_client.post(
        "/api/kill-switch", headers=headers, json={"engage": True, "reason": "conformance"}
    )
    assert engaged.status_code == 200, engaged.text
    assert engaged.json()["engaged"] is True

    state = await spec_client.get("/api/kill-switch", headers=headers)
    assert state.json()["engaged"] is True
    assert state.json()["reason"] == "conformance"

    blocked = await spec_client.post(
        "/api/runs", headers=headers, json={"agent_id": agent_a["id"], "directive": "go"}
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "emergency_stop_engaged"

    starting = await spec_client.post(f"/api/runs/{run['id']}/start", headers=headers)
    assert starting.status_code == 409, starting.text
    assert starting.json()["error"]["code"] == "emergency_stop_engaged"

    cleared = await spec_client.post("/api/kill-switch", headers=headers, json={"engage": False})
    assert cleared.status_code == 200
    assert cleared.json()["engaged"] is False
    allowed = await spec_client.post(
        "/api/runs", headers=headers, json={"agent_id": agent_a["id"], "directive": "go"}
    )
    assert allowed.status_code == 201, allowed.text


async def test_kill_switch_state_survives_a_restart(
    spec_client: AsyncClient,
    tenant_a: dict[str, Any],
    spec_settings: Settings,
    spec_engine: AsyncEngine,
) -> None:
    """The stop is stored in the database, so a new process cannot clear it (§3.2)."""
    headers = tenant_a["headers"]
    engaged = await spec_client.post("/api/kill-switch", headers=headers, json={"engage": True})
    assert engaged.status_code == 200

    restarted = _bind(create_app(spec_settings), spec_engine)  # fresh app object
    async with AsyncClient(
        transport=ASGITransport(app=restarted), base_url="http://spec.test"
    ) as fresh:
        state = await fresh.get("/api/kill-switch", headers=headers)
        assert state.status_code == 200, state.text
        assert state.json()["engaged"] is True


async def test_kill_switch_is_idempotent_and_emits_one_event_per_transition(
    spec_client: AsyncClient, tenant_a: dict[str, Any]
) -> None:
    headers = tenant_a["headers"]
    assert (
        await spec_client.post("/api/kill-switch", headers=headers, json={"engage": True})
    ).status_code == 200
    repeated = await spec_client.post("/api/kill-switch", headers=headers, json={"engage": True})
    assert repeated.status_code == 409, repeated.text
    assert repeated.json()["error"]["code"] == "emergency_stop_unchanged"

    assert (
        await spec_client.post("/api/kill-switch", headers=headers, json={"engage": False})
    ).status_code == 200

    engaged_events = await spec_client.get(
        "/api/events", headers=headers, params={"event_type": "emergency_stop.engaged"}
    )
    cleared_events = await spec_client.get(
        "/api/events", headers=headers, params={"event_type": "emergency_stop.cleared"}
    )
    assert len(engaged_events.json()) == 1
    assert len(cleared_events.json()) == 1

    audit_rows = await _audit(spec_client, headers, "system.emergency_stop")
    assert len(audit_rows) == 2
    assert {row["context"]["engage"] for row in audit_rows} == {True, False}


async def test_only_system_write_can_operate_the_kill_switch(
    spec_client: AsyncClient, tenant_a: dict[str, Any], viewer_a: dict[str, Any]
) -> None:
    """A read-only member cannot disarm the emergency stop (SPEC §13.2)."""
    owner_engaged = await spec_client.post(
        "/api/kill-switch", headers=tenant_a["headers"], json={"engage": True}
    )
    assert owner_engaged.status_code == 200

    denied = await spec_client.post(
        "/api/kill-switch", headers=viewer_a["headers"], json={"engage": False}
    )
    assert denied.status_code == 403, denied.text

    still_engaged = await spec_client.get("/api/kill-switch", headers=tenant_a["headers"])
    assert still_engaged.json()["engaged"] is True


# =========================================================================== #
# Optional live smoke test against a running local backend
# =========================================================================== #
async def test_live_local_backend_smoke() -> None:
    """Read-only checks against ``NEXUS_BASE_URL`` when a local server is running.

    Skipped (with a recorded reason) when no server URL is provided. It mutates
    nothing, so it is safe against an owner's working database.
    """
    base_url = os.environ.get("NEXUS_BASE_URL")
    if not base_url:
        pytest.skip("NEXUS_BASE_URL is not set; no live backend to probe (recorded skip).")

    import httpx

    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=10.0) as http:
        health = await http.get("/api/health")
        assert health.status_code == 200, health.text
        assert health.json()["status"] == "ok"
        assert health.json()["database"] == "ok"

        for path in ("/api/agents", "/api/audit", "/api/system/autonomy"):
            unauthenticated = await http.get(path)
            assert unauthenticated.status_code == 401, f"{path} -> {unauthenticated.status_code}"
            assert unauthenticated.json()["error"]["code"]

        # The kill switch must never accept an unauthenticated command.
        assert (await http.post("/api/kill-switch", json={"engage": False})).status_code == 401
