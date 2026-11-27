"""Conformance tests for the NEXUS AGENT OS backend (docs/SPEC.md).

Task AATM-e4103400: covers the four §9 conformance areas against the locally
running backend.

1. **Event sequencing** (docs/SPEC.md §7, §4.3): every event document matches
   the §7 field list, ``sequence`` is strictly monotonically increasing per
   run (including under concurrent submissions), and a client can replay a
   run's event stream from the last sequence it has seen.
2. **RBAC** (§2 Phase 2): protected routes reject anonymous callers with 401;
   roles ``owner | admin | member | viewer`` are enforced with 403; data is
   organization-scoped (org B cannot read org A's runs/events/approvals).
3. **Tool Gateway** (§3.2, §13.2): arguments are validated against JSON
   Schema; the action policy decides ``allow | ask | deny`` per autonomy
   level; ``http_get`` is allow-listed by host and routed through the
   approval hook; every decision — allow, ask or deny — is audited.
4. **Emergency stop** (§3.2): the global kill switch is available in every
   autonomy level, cancels active runs within 2 seconds, blocks new work
   while engaged, and records ``emergency_stop.engaged`` / ``cleared``
   events.

Run modes
---------
* **Default** (no environment variable): the suite starts the FastAPI app
  in-process (httpx ASGI transport) against a throwaway SQLite database and
  Alembic migrations. This is what ``scripts/check.sh`` and CI's ``check``
  job run.
* **Live backend**: set ``NEXUS_API_BASE_URL`` (or ``API_BASE_URL``) to point
  at a running server, e.g.::

      uvicorn backend.app.main:app --port 8000
      NEXUS_API_BASE_URL=http://127.0.0.1:8000 pytest tests/test_spec_conformance.py

  In live mode the suite bootstraps the first-run owner (or logs in with
  ``E2E_OWNER_EMAIL`` / ``E2E_OWNER_PASSWORD`` — throwaway test-only values,
  never real credentials). A missing/unreachable backend FAILS the suite
  (no silent skip).
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest

from backend.app.core.config import Settings
from backend.app.core.db import run_migrations
from backend.app.core.redaction import redact_value
from backend.app.main import create_app

# Throwaway test-only values (documented, not real credentials).
OWNER_EMAIL_DEFAULT = "e2e-owner@example.com"
OWNER_PASSWORD_DEFAULT = "e2e-test-only-throwaway-pass"

SPEC_EVENT_FIELDS = [
    "event_id",
    "event_version",
    "organization_id",
    "run_id",
    "task_id",
    "agent_id",
    "correlation_id",
    "sequence",
    "event_type",
    "timestamp",
    "source_runtime",
    "payload",
]


# ---------------------------------------------------------------------------
# Client plumbing
# ---------------------------------------------------------------------------


class ConformanceAPI:
    """Thin httpx wrapper that attaches a bearer token when given."""

    def __init__(self, http: httpx.AsyncClient, live: bool) -> None:
        self.http = http
        self.live = live

    async def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return await self.http.request(method, path, json=json, params=params, headers=headers)

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", path, **kwargs)


@dataclass
class Auth:
    token: str
    refresh_token: str
    user: dict[str, Any]


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.test"


@pytest.fixture
async def api() -> Any:
    """Yield a ConformanceAPI bound to a live backend or an in-process app."""
    base = os.environ.get("NEXUS_API_BASE_URL") or os.environ.get("API_BASE_URL")
    if base:
        async with httpx.AsyncClient(base_url=base, timeout=60.0) as http:
            yield ConformanceAPI(http, live=True)
        return

    tmp = tempfile.mkdtemp(prefix="nexus-conformance-")
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp}/conformance.db",
        jwt_secret=secrets.token_urlsafe(48),
    )
    await asyncio.to_thread(run_migrations, settings.database_url)
    app = create_app(settings)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://conformance", timeout=60.0
        ) as http:
            yield ConformanceAPI(http, live=False)
    finally:
        await app.state.engine.dispose()
        shutil.rmtree(tmp, ignore_errors=True)


async def _bootstrap_or_login(api: ConformanceAPI) -> Auth:
    """First-run bootstrap; fall back to login on an already-bootstrapped DB."""
    email = os.environ.get("E2E_OWNER_EMAIL", OWNER_EMAIL_DEFAULT)
    password = os.environ.get("E2E_OWNER_PASSWORD", OWNER_PASSWORD_DEFAULT)
    response = await api.post("/api/auth/bootstrap", json={"email": email, "password": password})
    if response.status_code == 409:
        response = await api.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, (
        f"cannot obtain an owner session against {api.http.base_url}: "
        f"{response.status_code} {response.text}"
    )
    body = response.json()
    return Auth(token=body["access_token"], refresh_token=body["refresh_token"], user=body["user"])


@pytest.fixture
async def owner(api: ConformanceAPI) -> Auth:
    return await _bootstrap_or_login(api)


# --- shared flow helpers -----------------------------------------------------


async def _create_run(
    api: ConformanceAPI,
    token: str,
    goal: str = "conformance run",
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"goal": goal, **overrides}
    response = await api.post("/api/runs", token=token, json=payload)
    assert response.status_code == 201, f"POST /api/runs → {response.status_code} {response.text}"
    return response.json()


async def _start_run(api: ConformanceAPI, token: str, run_id: str) -> dict[str, Any]:
    response = await api.post(f"/api/runs/{run_id}/start", token=token)
    assert response.status_code == 200, response.text
    return response.json()


async def _submit_tool(
    api: ConformanceAPI,
    token: str,
    run_id: str,
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    expect: int = 201,
) -> httpx.Response:
    response = await api.post(
        f"/api/runs/{run_id}/tool-calls",
        token=token,
        json={"tool": tool, "arguments": arguments or {}},
    )
    assert response.status_code == expect, (
        f"tool call {tool} → {response.status_code} (expected {expect}): {response.text}"
    )
    return response


async def _run_events(
    api: ConformanceAPI, token: str, run_id: str, after: int | None = None
) -> list[dict[str, Any]]:
    params = {"after": after} if after is not None else None
    response = await api.get(f"/api/runs/{run_id}/events", token=token, params=params)
    assert response.status_code == 200, response.text
    return response.json()["events"]


async def _pending_approval_for_run(api: ConformanceAPI, token: str, run_id: str) -> dict[str, Any]:
    """The single pending approval of this run (scoped, never cross-run)."""
    response = await api.get(
        "/api/approvals", token=token, params={"approval_status": "pending", "run_id": run_id}
    )
    assert response.status_code == 200, response.text
    pending = response.json()
    assert len(pending) == 1, f"expected exactly one pending approval for {run_id}: {pending}"
    return pending[0]


async def _ensure_kill_switch_cleared(api: ConformanceAPI, token: str) -> None:
    """Best-effort cleanup so an emergency stop never leaks across tests."""
    await api.post("/api/system/emergency-stop/clear", token=token)


class _Handler(BaseHTTPRequestHandler):
    """Minimal JSON endpoint for the allow-listed http_get journey."""

    def do_GET(self) -> None:
        body = json.dumps({"ok": True, "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:  # keep test output clean
        pass


@pytest.fixture
def local_http_url() -> Any:
    """A real loopback HTTP server (127.0.0.1 is allow-listed by default)."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/data"
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# 0. Health & auth surface (§2; Q5 unauthenticated checks)
# ---------------------------------------------------------------------------


class TestHealthAndAuthSurface:
    async def test_health_endpoint_is_public_and_reports_database(
        self, api: ConformanceAPI
    ) -> None:
        response = await api.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("GET", "/api/auth/me", None),
            ("GET", "/api/runs", None),
            ("POST", "/api/runs", {"goal": "x"}),
            ("POST", "/api/runs/run_x/start", None),
            ("GET", "/api/runs/run_x/events", None),
            ("POST", "/api/runs/run_x/tool-calls", {"tool": "calculator"}),
            ("GET", "/api/tools", None),
            ("GET", "/api/tool-calls", None),
            ("GET", "/api/approvals", None),
            ("POST", "/api/approvals/appr_x/approve", None),
            ("POST", "/api/approvals/appr_x/reject", None),
            ("GET", "/api/events", None),
            ("POST", "/api/users", {"email": "x@example.test", "password": "longenough1"}),
            ("POST", "/api/organizations", {"name": "x"}),
            ("GET", "/api/system/emergency-stop", None),
            ("POST", "/api/system/emergency-stop", {"reason": "x"}),
            ("POST", "/api/system/emergency-stop/clear", None),
        ],
    )
    async def test_protected_routes_reject_anonymous_requests(
        self, api: ConformanceAPI, method: str, path: str, body: dict[str, Any] | None
    ) -> None:
        """Q5: every non-public route requires authentication (401 without)."""
        response = await api.request(method, path, json=body)
        assert response.status_code == 401, f"{method} {path} → {response.status_code}"

    async def test_invalid_bearer_token_is_rejected(self, api: ConformanceAPI) -> None:
        response = await api.get("/api/auth/me", token="not-a-real-jwt")
        assert response.status_code == 401

    async def test_wrong_credentials_are_rejected(self, api: ConformanceAPI, owner: Auth) -> None:
        response = await api.post(
            "/api/auth/login", json={"email": owner.user["email"], "password": "definitely-wrong"}
        )
        assert response.status_code == 401
        unknown = await api.post(
            "/api/auth/login", json={"email": _unique_email("nobody"), "password": "whatever123"}
        )
        assert unknown.status_code == 401

    async def test_refresh_flow_issues_a_working_access_token(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        refreshed = await api.post("/api/auth/refresh", json={"refresh_token": owner.refresh_token})
        assert refreshed.status_code == 200
        new_access = refreshed.json()["access_token"]
        me = await api.get("/api/auth/me", token=new_access)
        assert me.status_code == 200
        assert me.json()["role"] == "owner"
        # A refresh token must NOT work as an access token.
        assert (await api.get("/api/auth/me", token=owner.refresh_token)).status_code == 401


# ---------------------------------------------------------------------------
# 1. Event sequencing (docs/SPEC.md §7 + §4.3)
# ---------------------------------------------------------------------------


class TestEventSequenceMonotonic:
    async def test_events_match_the_spec_document_shape(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        run = await _create_run(api, owner.token)
        await _start_run(api, owner.token, run["id"])
        await _submit_tool(api, owner.token, run["id"], "calculator", {"expression": "20+22"})
        await api.post(f"/api/runs/{run['id']}/complete", token=owner.token)

        events = await _run_events(api, owner.token, run["id"])
        assert len(events) >= 5
        for event in events:
            for field in SPEC_EVENT_FIELDS:
                assert field in event, f"missing §7 field {field!r} in {event}"
            assert event["run_id"] == run["id"]
            assert event["source_runtime"] == "native"
            assert isinstance(event["payload"], dict)
            # timestamp is ISO-8601 UTC with a Z suffix (§7 example format)
            assert event["timestamp"].endswith("Z")
        assert events[0]["event_type"] == "run.created"
        assert {e["event_type"] for e in events} >= {
            "run.created",
            "run.started",
            "tool.execution.started",
            "tool.execution.completed",
            "run.completed",
        }

    async def test_sequence_is_strictly_monotonic_per_run(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        run = await _create_run(api, owner.token)
        await _start_run(api, owner.token, run["id"])
        for _ in range(3):
            await _submit_tool(api, owner.token, run["id"], "calculator", {"expression": "2*3"})

        events = await _run_events(api, owner.token, run["id"])
        sequences = [event["sequence"] for event in events]
        assert sequences[0] == 1
        for previous, current in itertools.pairwise(sequences):
            assert current == previous + 1, f"non-monotonic: {sequences}"

    async def test_concurrent_submissions_keep_sequence_unique_and_monotonic(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        run = await _create_run(api, owner.token, autonomy_level=3)
        await _start_run(api, owner.token, run["id"])

        responses = await asyncio.gather(
            *[
                _submit_tool(api, owner.token, run["id"], "calculator", {"expression": f"{i}+{i}"})
                for i in range(8)
            ]
        )
        assert all(r.json()["status"] == "completed" for r in responses)

        events = await _run_events(api, owner.token, run["id"])
        started = [e for e in events if e["event_type"] == "tool.execution.started"]
        assert len(started) == 8
        sequences = [e["sequence"] for e in sorted(started, key=lambda e: e["sequence"])]
        assert len(set(sequences)) == len(sequences), f"duplicate sequences: {sequences}"
        for previous, current in itertools.pairwise(sequences):
            assert current > previous, f"non-monotonic under concurrency: {sequences}"

    async def test_replay_from_last_event_id_returns_only_newer_events(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        run = await _create_run(api, owner.token)
        await _start_run(api, owner.token, run["id"])
        await _submit_tool(api, owner.token, run["id"], "calculator", {"expression": "1+1"})

        all_events = await _run_events(api, owner.token, run["id"])
        assert len(all_events) >= 3
        last_seen = all_events[1]["sequence"]

        replay = await _run_events(api, owner.token, run["id"], after=last_seen)
        assert [e["sequence"] for e in replay] == [
            e["sequence"] for e in all_events if e["sequence"] > last_seen
        ]
        newest = all_events[-1]["sequence"]
        assert await _run_events(api, owner.token, run["id"], after=newest) == []


# ---------------------------------------------------------------------------
# 2. RBAC (docs/SPEC.md §2 Phase 2)
# ---------------------------------------------------------------------------


class TestRBAC:
    async def test_viewer_is_read_only(self, api: ConformanceAPI, owner: Auth) -> None:
        viewer_email = _unique_email("viewer")
        created = await api.post(
            "/api/users",
            token=owner.token,
            json={"email": viewer_email, "password": "viewer-pass-123", "role": "viewer"},
        )
        assert created.status_code == 201
        login = await api.post(
            "/api/auth/login", json={"email": viewer_email, "password": "viewer-pass-123"}
        )
        assert login.status_code == 200
        viewer_token = login.json()["access_token"]

        assert (await api.get("/api/runs", token=viewer_token)).status_code == 200
        assert (await api.get("/api/tool-calls", token=viewer_token)).status_code == 200
        assert (await api.get("/api/approvals", token=viewer_token)).status_code == 200

        assert (
            await api.post("/api/runs", token=viewer_token, json={"goal": "nope"})
        ).status_code == 403
        assert (
            await api.post(
                "/api/users",
                token=viewer_token,
                json={"email": _unique_email("v"), "password": "viewer-pass-123"},
            )
        ).status_code == 403
        assert (
            await api.post(
                "/api/system/emergency-stop", token=viewer_token, json={"reason": "nope"}
            )
        ).status_code == 403

        run = await _create_run(api, owner.token)
        assert (
            await api.post(
                f"/api/runs/{run['id']}/tool-calls",
                token=viewer_token,
                json={"tool": "calculator", "arguments": {"expression": "1"}},
            )
        ).status_code == 403

    async def test_member_can_run_tools_but_cannot_approve_or_administer(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        member_email = _unique_email("member")
        created = await api.post(
            "/api/users",
            token=owner.token,
            json={"email": member_email, "password": "member-pass-123", "role": "member"},
        )
        assert created.status_code == 201
        login = await api.post(
            "/api/auth/login", json={"email": member_email, "password": "member-pass-123"}
        )
        member_token = login.json()["access_token"]

        # Level 0: every tool call is routed to approval (ask).
        run = await _create_run(api, member_token, autonomy_level=0)
        await _start_run(api, member_token, run["id"])
        call = await _submit_tool(api, member_token, run["id"], "calculator", {"expression": "1+2"})
        assert call.json()["policy_decision"] == "ask"
        approval = await _pending_approval_for_run(api, member_token, run["id"])

        # Members cannot approve (§2: approvals are a human/admin decision).
        assert (
            await api.post(f"/api/approvals/{approval['id']}/approve", token=member_token)
        ).status_code == 403
        # Members cannot manage users or organizations.
        assert (
            await api.post(
                "/api/users",
                token=member_token,
                json={"email": _unique_email("m"), "password": "member-pass-123"},
            )
        ).status_code == 403
        assert (
            await api.post("/api/organizations", token=member_token, json={"name": "nope"})
        ).status_code == 403
        assert (
            await api.post(
                "/api/system/emergency-stop", token=member_token, json={"reason": "nope"}
            )
        ).status_code == 403

    async def test_admin_can_approve_and_manage_users_but_not_create_organizations(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        admin_email = _unique_email("admin")
        created = await api.post(
            "/api/users",
            token=owner.token,
            json={"email": admin_email, "password": "admin-pass-1234", "role": "admin"},
        )
        assert created.status_code == 201
        admin_token = (
            await api.post(
                "/api/auth/login", json={"email": admin_email, "password": "admin-pass-1234"}
            )
        ).json()["access_token"]

        run = await _create_run(api, owner.token, autonomy_level=0)
        await _start_run(api, owner.token, run["id"])
        await _submit_tool(api, owner.token, run["id"], "calculator", {"expression": "6*7"})
        approval = await _pending_approval_for_run(api, admin_token, run["id"])

        approved = await api.post(f"/api/approvals/{approval['id']}/approve", token=admin_token)
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
        calls = (
            await api.get("/api/tool-calls", token=admin_token, params={"run_id": run["id"]})
        ).json()
        assert calls[-1]["status"] == "completed"
        assert calls[-1]["result"]["result"] == 42

        # Admins can provision users inside their organization…
        provisioned = await api.post(
            "/api/users",
            token=admin_token,
            json={
                "email": _unique_email("by-admin"),
                "password": "admin-pass-1234",
                "role": "viewer",
            },
        )
        assert provisioned.status_code == 201
        # …but cannot create organizations (owner-only)…
        assert (
            await api.post("/api/organizations", token=admin_token, json={"name": "nope"})
        ).status_code == 403
        # …and cannot decide an approval twice (409).
        assert (
            await api.post(f"/api/approvals/{approval['id']}/approve", token=admin_token)
        ).status_code == 409

    async def test_owner_can_create_organizations_and_provision_across_them(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        org = await api.post("/api/organizations", token=owner.token, json={"name": "Org B"})
        assert org.status_code == 201
        org_b_id = org.json()["id"]

        member_b = await api.post(
            f"/api/organizations/{org_b_id}/users",
            token=owner.token,
            json={"email": _unique_email("orgb"), "password": "orgb-pass-1234", "role": "member"},
        )
        assert member_b.status_code == 201
        assert member_b.json()["organization_id"] == org_b_id

    async def test_organization_data_is_isolated(self, api: ConformanceAPI, owner: Auth) -> None:
        # A member of org B must not see org A's data (§2: "a user of org A
        # cannot see org B's data").
        org = await api.post("/api/organizations", token=owner.token, json={"name": "Org B"})
        org_b_id = org.json()["id"]
        member_b_email = _unique_email("orgb")
        await api.post(
            f"/api/organizations/{org_b_id}/users",
            token=owner.token,
            json={"email": member_b_email, "password": "orgb-pass-1234", "role": "member"},
        )
        member_b_token = (
            await api.post(
                "/api/auth/login", json={"email": member_b_email, "password": "orgb-pass-1234"}
            )
        ).json()["access_token"]

        run_a = await _create_run(api, owner.token)
        await _start_run(api, owner.token, run_a["id"])
        await _submit_tool(api, owner.token, run_a["id"], "calculator", {"expression": "1+1"})

        # Org B sees only its own (empty) data, never org A's records.
        assert (await api.get("/api/runs", token=member_b_token)).json() == []
        assert (await api.get(f"/api/runs/{run_a['id']}", token=member_b_token)).status_code == 404
        assert (
            await api.get(f"/api/runs/{run_a['id']}/events", token=member_b_token)
        ).status_code == 404
        assert (await api.get("/api/tool-calls", token=member_b_token)).json() == []
        assert (await api.get("/api/approvals", token=member_b_token)).json() == []
        assert (await api.get("/api/events", token=member_b_token)).json()["events"] == []

        # And org B cannot mutate org A's resources (404 — no existence leak).
        assert (
            await api.post(f"/api/runs/{run_a['id']}/cancel", token=member_b_token)
        ).status_code == 404


# ---------------------------------------------------------------------------
# 3. Tool Gateway (docs/SPEC.md §3.2, §13.2)
# ---------------------------------------------------------------------------


class TestToolGateway:
    async def test_registry_exposes_json_schema_for_every_tool(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        tools = (await api.get("/api/tools", token=owner.token)).json()["tools"]
        names = {t["name"] for t in tools}
        assert {"calculator", "current_time", "knowledge_search", "http_get"} <= names
        for tool in tools:
            assert isinstance(tool["input_schema"], dict) and tool["input_schema"]
        http_get = next(t for t in tools if t["name"] == "http_get")
        assert http_get["requires_approval"] is True

    async def test_unknown_tool_is_404_and_still_audited_as_deny(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        run = await _create_run(api, owner.token)
        await _start_run(api, owner.token, run["id"])
        await _submit_tool(
            api, owner.token, run["id"], "definitely_not_a_tool", {"x": 1}, expect=404
        )
        audit = (
            await api.get("/api/tool-calls", token=owner.token, params={"run_id": run["id"]})
        ).json()
        assert audit and audit[-1]["policy_decision"] == "deny"
        assert audit[-1]["policy_reason"] == "unknown_tool"

    async def test_arguments_failing_json_schema_are_422_and_audited(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        run = await _create_run(api, owner.token)
        await _start_run(api, owner.token, run["id"])
        # Wrong argument type (schema wants string)…
        await _submit_tool(api, owner.token, run["id"], "calculator", {"expression": 5}, expect=422)
        # …and an argument key the schema does not allow.
        await _submit_tool(
            api,
            owner.token,
            run["id"],
            "calculator",
            {"expression": "1+1", "extra": "nope"},
            expect=422,
        )
        audit = (
            await api.get("/api/tool-calls", token=owner.token, params={"run_id": run["id"]})
        ).json()
        assert len(audit) == 2
        assert all(row["policy_decision"] == "deny" for row in audit)
        assert all(row["policy_reason"] == "invalid_arguments" for row in audit)
        assert all(row["status"] == "denied" for row in audit)

    async def test_dangerous_expression_is_never_executed(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        run = await _create_run(api, owner.token)
        await _start_run(api, owner.token, run["id"])
        response = await _submit_tool(
            api,
            owner.token,
            run["id"],
            "calculator",
            {"expression": "__import__('os').listdir('.')"},
        )
        assert response.json()["status"] == "failed"
        assert response.json()["result"] is None
        assert "calculator" in response.json()["error"]

        events = await _run_events(api, owner.token, run["id"])
        types = {e["event_type"] for e in events}
        assert "tool.execution.failed" in types
        assert "tool.execution.completed" not in types

    async def test_run_tool_allow_list_denies_other_registered_tools(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        run = await _create_run(api, owner.token, allowed_tools=["calculator"])
        await _start_run(api, owner.token, run["id"])
        response = await _submit_tool(api, owner.token, run["id"], "current_time")
        assert response.json()["policy_decision"] == "deny"
        assert response.json()["policy_reason"] == "not_in_run_allow_list"
        assert response.json()["status"] == "denied"

        events = await _run_events(api, owner.token, run["id"])
        assert not any(e["event_type"].startswith("tool.execution") for e in events)

    async def test_http_get_denied_for_non_allowlisted_host(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        run = await _create_run(api, owner.token)
        await _start_run(api, owner.token, run["id"])
        response = await _submit_tool(
            api, owner.token, run["id"], "http_get", {"url": "http://example.com/steal"}
        )
        assert response.json()["policy_decision"] == "deny"
        assert response.json()["policy_reason"] == "host_not_in_allowlist"
        assert response.json()["status"] == "denied"
        assert response.json()["result"] is None

    async def test_http_get_requires_approval_then_executes_allowlisted_host(
        self, api: ConformanceAPI, owner: Auth, local_http_url: str
    ) -> None:
        run = await _create_run(api, owner.token)
        await _start_run(api, owner.token, run["id"])

        submitted = await _submit_tool(
            api, owner.token, run["id"], "http_get", {"url": local_http_url}
        )
        assert submitted.json()["status"] == "pending_approval"
        assert submitted.json()["policy_decision"] == "ask"

        events = await _run_events(api, owner.token, run["id"])
        assert any(e["event_type"] == "approval.requested" for e in events)
        approval = await _pending_approval_for_run(api, owner.token, run["id"])

        approved = await api.post(f"/api/approvals/{approval['id']}/approve", token=owner.token)
        assert approved.status_code == 200

        audit = (
            await api.get("/api/tool-calls", token=owner.token, params={"run_id": run["id"]})
        ).json()
        assert audit[-1]["status"] == "completed"
        result = audit[-1]["result"]
        assert result["status_code"] == 200
        assert result["body"] == json.dumps({"ok": True, "path": "/data"})
        assert audit[-1]["duration_ms"] is not None

        events = await _run_events(api, owner.token, run["id"])
        assert any(e["event_type"] == "approval.approved" for e in events)
        assert any(e["event_type"] == "tool.execution.completed" for e in events)

    async def test_http_get_to_a_closed_port_records_failed_execution(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        run = await _create_run(api, owner.token)
        await _start_run(api, owner.token, run["id"])
        await _submit_tool(api, owner.token, run["id"], "http_get", {"url": "http://127.0.0.1:9/x"})
        approval = await _pending_approval_for_run(api, owner.token, run["id"])
        assert (
            await api.post(f"/api/approvals/{approval['id']}/approve", token=owner.token)
        ).status_code == 200
        audit = (
            await api.get("/api/tool-calls", token=owner.token, params={"run_id": run["id"]})
        ).json()
        assert audit[-1]["status"] == "failed"
        assert audit[-1]["error"]
        events = await _run_events(api, owner.token, run["id"])
        assert any(e["event_type"] == "tool.execution.failed" for e in events)

    async def test_level_0_policy_asks_for_every_tool(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        run = await _create_run(api, owner.token, autonomy_level=0)
        await _start_run(api, owner.token, run["id"])
        response = await _submit_tool(
            api, owner.token, run["id"], "calculator", {"expression": "1+1"}
        )
        assert response.json()["policy_decision"] == "ask"
        assert response.json()["status"] == "pending_approval"

    async def test_higher_levels_allow_builtins_without_approval(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        for level in (1, 2, 3):
            run = await _create_run(api, owner.token, autonomy_level=level)
            await _start_run(api, owner.token, run["id"])
            response = await _submit_tool(
                api, owner.token, run["id"], "calculator", {"expression": "21*2"}
            )
            body = response.json()
            assert body["policy_decision"] == "allow", f"level {level}: {body}"
            assert body["policy_reason"] == f"level_{level}_policy"
            assert body["status"] == "completed"
            assert body["result"]["result"] == 42

    async def test_knowledge_search_honestly_reports_not_configured(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        run = await _create_run(api, owner.token)
        await _start_run(api, owner.token, run["id"])
        response = await _submit_tool(
            api, owner.token, run["id"], "knowledge_search", {"query": "anything"}
        )
        assert response.json()["result"]["status"] == "not_configured"

    async def test_every_gateway_decision_is_audited(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        run = await _create_run(api, owner.token, allowed_tools=["calculator"])
        await _start_run(api, owner.token, run["id"])
        await _submit_tool(api, owner.token, run["id"], "calculator", {"expression": "1"})  # allow
        await _submit_tool(api, owner.token, run["id"], "current_time", expect=201)  # deny
        await _submit_tool(
            api, owner.token, run["id"], "calculator", {"expression": 5}, expect=422
        )  # deny (schema)
        await _submit_tool(api, owner.token, run["id"], "nope", expect=404)  # deny (unknown)

        audit = (
            await api.get("/api/tool-calls", token=owner.token, params={"run_id": run["id"]})
        ).json()
        assert len(audit) == 4  # one audit row per submission, including 404/422
        for row in audit:
            assert row["policy_decision"] in ("allow", "ask", "deny")
            assert row["policy_reason"]
            assert row["requested_by"] == owner.user["id"]
            assert row["created_at"].endswith("Z")


# ---------------------------------------------------------------------------
# 4. Emergency stop / kill switch (docs/SPEC.md §3.2)
# ---------------------------------------------------------------------------


class TestEmergencyStop:
    async def test_engage_cancels_active_runs_within_two_seconds(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        runs = [await _create_run(api, owner.token) for _ in range(2)]
        for run in runs:
            await _start_run(api, owner.token, run["id"])

        try:
            started = time.perf_counter()
            engage = await api.post(
                "/api/system/emergency-stop", token=owner.token, json={"reason": "conformance"}
            )
            elapsed = time.perf_counter() - started
            assert engage.status_code == 200
            assert engage.json()["engaged"] is True
            # Every active run is cancelled — at least the two this test
            # started (a shared live database may hold more from other tests).
            assert engage.json()["cancelled_runs"] >= 2
            assert elapsed < 2.0, f"kill switch took {elapsed:.3f}s (must stop within 2s)"

            for run in runs:
                state = (await api.get(f"/api/runs/{run['id']}", token=owner.token)).json()
                assert state["status"] == "cancelled"
                events = await _run_events(api, owner.token, run["id"])
                cancelled = [e for e in events if e["event_type"] == "run.cancelled"]
                assert cancelled and cancelled[-1]["payload"]["reason"] == "emergency_stop_engaged"
        finally:
            await _ensure_kill_switch_cleared(api, owner.token)

    async def test_engagement_blocks_new_work_until_cleared(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        pending = await _create_run(api, owner.token)
        try:
            assert (
                await api.post(
                    "/api/system/emergency-stop", token=owner.token, json={"reason": "halt"}
                )
            ).status_code == 200
            assert (
                await api.post("/api/runs", token=owner.token, json={"goal": "blocked"})
            ).status_code == 409
            assert (
                await api.post(f"/api/runs/{pending['id']}/start", token=owner.token)
            ).status_code == 409
            assert (
                await api.post(
                    f"/api/runs/{pending['id']}/tool-calls",
                    token=owner.token,
                    json={"tool": "calculator", "arguments": {"expression": "1"}},
                )
            ).status_code == 409
            state = (await api.get("/api/system/emergency-stop", token=owner.token)).json()
            assert state["engaged"] is True and state["engaged_at"]
        finally:
            cleared = await api.post("/api/system/emergency-stop/clear", token=owner.token)
            assert cleared.status_code == 200

        fresh = await api.post("/api/runs", token=owner.token, json={"goal": "after clear"})
        assert fresh.status_code == 201
        assert (
            await api.post(f"/api/runs/{fresh.json()['id']}/start", token=owner.token)
        ).status_code == 200

    async def test_kill_switch_is_available_in_every_autonomy_level(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        """docs/SPEC.md §3.2: the kill switch cannot be disabled in any level."""
        try:
            for level in range(4):
                run = await _create_run(api, owner.token, autonomy_level=level)
                await _start_run(api, owner.token, run["id"])
                engage = await api.post(
                    "/api/system/emergency-stop",
                    token=owner.token,
                    json={"reason": f"level {level}"},
                )
                assert engage.status_code == 200, f"level {level}: kill switch unavailable"
                state = (await api.get(f"/api/runs/{run['id']}", token=owner.token)).json()
                assert state["status"] == "cancelled"
                clear = await api.post("/api/system/emergency-stop/clear", token=owner.token)
                assert clear.status_code == 200, f"level {level}: clear failed"
        finally:
            await _ensure_kill_switch_cleared(api, owner.token)

    async def test_double_engage_and_clear_without_engage_conflict(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        try:
            assert (
                await api.post("/api/system/emergency-stop/clear", token=owner.token)
            ).status_code == 409
            assert (
                await api.post(
                    "/api/system/emergency-stop", token=owner.token, json={"reason": "first"}
                )
            ).status_code == 200
            assert (
                await api.post(
                    "/api/system/emergency-stop", token=owner.token, json={"reason": "second"}
                )
            ).status_code == 409
        finally:
            assert (
                await api.post("/api/system/emergency-stop/clear", token=owner.token)
            ).status_code == 200

    async def test_engage_and_clear_require_admin_or_owner(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        member_email = _unique_email("es-member")
        await api.post(
            "/api/users",
            token=owner.token,
            json={"email": member_email, "password": "member-pass-123", "role": "member"},
        )
        member_token = (
            await api.post(
                "/api/auth/login", json={"email": member_email, "password": "member-pass-123"}
            )
        ).json()["access_token"]
        viewer_email = _unique_email("es-viewer")
        await api.post(
            "/api/users",
            token=owner.token,
            json={"email": viewer_email, "password": "viewer-pass-123", "role": "viewer"},
        )
        viewer_token = (
            await api.post(
                "/api/auth/login", json={"email": viewer_email, "password": "viewer-pass-123"}
            )
        ).json()["access_token"]

        for token in (member_token, viewer_token):
            assert (
                await api.post("/api/system/emergency-stop", token=token, json={"reason": "nope"})
            ).status_code == 403
            assert (
                await api.post("/api/system/emergency-stop/clear", token=token)
            ).status_code == 403
        # The state itself is readable by every authenticated role.
        assert (await api.get("/api/system/emergency-stop", token=viewer_token)).status_code == 200

    async def test_emergency_stop_events_are_recorded_in_the_org_feed(
        self, api: ConformanceAPI, owner: Auth
    ) -> None:
        run = await _create_run(api, owner.token)
        await _start_run(api, owner.token, run["id"])
        try:
            assert (
                await api.post(
                    "/api/system/emergency-stop", token=owner.token, json={"reason": "feed check"}
                )
            ).status_code == 200
            assert (
                await api.post("/api/system/emergency-stop/clear", token=owner.token)
            ).status_code == 200
        finally:
            await _ensure_kill_switch_cleared(api, owner.token)

        engaged = (
            await api.get(
                "/api/events", token=owner.token, params={"event_type": "emergency_stop.engaged"}
            )
        ).json()["events"]
        cleared = (
            await api.get(
                "/api/events", token=owner.token, params={"event_type": "emergency_stop.cleared"}
            )
        ).json()["events"]
        assert engaged and cleared
        assert engaged[-1]["payload"]["reason"] == "feed check"
        assert run["id"] in engaged[-1]["payload"]["cancelled_runs"]
        # Global events share the global (run_id NULL) sequence stream: strictly increasing.
        assert cleared[-1]["sequence"] > engaged[-1]["sequence"]

        state = (await api.get("/api/system/emergency-stop", token=owner.token)).json()
        assert state["engaged"] is False
        assert state["cleared_at"] is not None


# ---------------------------------------------------------------------------
# §7 payload redaction (defense-in-depth pipeline)
# ---------------------------------------------------------------------------


def test_payload_redaction_replaces_sensitive_keys_recursively() -> None:
    payload = {
        "headers": {"Authorization": "Bearer secret-value", "Accept": "application/json"},
        "nested": {"api_key": "k", "safe": 1, "deeper": {"user_token": "t"}},
        "list": [{"password": "p"}, {"plain": "ok"}],
    }
    redacted = redact_value(payload)
    assert redacted["headers"]["Authorization"] == "***"
    assert redacted["headers"]["Accept"] == "application/json"
    assert redacted["nested"]["api_key"] == "***"
    assert redacted["nested"]["safe"] == 1
    assert redacted["nested"]["deeper"]["user_token"] == "***"
    assert redacted["list"][0]["password"] == "***"
    assert redacted["list"][1]["plain"] == "ok"
    # The original payload must be untouched (redaction returns a copy).
    assert payload["headers"]["Authorization"] == "Bearer secret-value"
