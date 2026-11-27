"""Backend acceptance tests for docs/SPEC.md (AATM-e7410b2b).

Coverage map to the specification:
- §6 Phase 2.1  auth: first-run setup, argon2, lockout, refresh rotation, RBAC.
- §6 Phase 2.2  models and Alembic: every required table exists.
- §6 Phase 2.5  agents: create/edit/clone/enable and immutable versions.
- §6 Phase 2.7  Tool Gateway: JSON Schema validation, allow-list, audit, approval.
- §4.3 / §7     events: outbox write, per-run monotonic sequence, replay.
- §3.2 / §13    kill switch, action policy, audit, secret handling.
- §1 / §6 P3    missions, task DAG validation, 8-step timeline.
- §8.3-I        Connection Manager: terms acknowledgement, pairing, adapters.
- §5.3/§3.3     honesty: usage reported as null, capabilities never guessed.
"""

from __future__ import annotations

import pytest

from tests.conftest import TEST_PASSWORD, VIEWER_PASSWORD

# --------------------------------------------------------------------------- #
# §6 Phase 2.2 — schema completeness
# --------------------------------------------------------------------------- #
REQUIRED_TABLES = {
    "users",
    "organizations",
    "organization_members",
    "role_grants",
    "permissions",
    "credentials",
    "providers",
    "provider_connections",
    "browser_devices",
    "browser_profiles",
    "browser_sessions",
    "adapters",
    "agents",
    "agent_versions",
    "conversations",
    "messages",
    "runs",
    "events",
    "tools",
    "approvals",
    "audit_logs",
}


@pytest.mark.asyncio
async def test_all_required_tables_exist(engine) -> None:
    from sqlalchemy import inspect

    async with engine.connect() as connection:
        tables = await connection.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )
    missing = REQUIRED_TABLES - tables
    assert not missing, f"missing tables required by SPEC Phase 2.2: {sorted(missing)}"


@pytest.mark.asyncio
async def test_tenant_scoped_tables_carry_organization_id(engine) -> None:
    """Every tenant-scoped table must carry organization_id (SPEC Phase 2.2)."""
    from sqlalchemy import inspect

    async with engine.connect() as connection:
        columns = await connection.run_sync(
            lambda sync_conn: {
                name: {col["name"] for col in inspect(sync_conn).get_columns(name)}
                for name in inspect(sync_conn).get_table_names()
            }
        )
    tenant_tables = {
        "agents",
        "agent_versions",
        "credentials",
        "providers",
        "provider_connections",
        "browser_devices",
        "browser_profiles",
        "browser_sessions",
        "adapters",
        "conversations",
        "messages",
        "runs",
        "events",
        "checkpoints",
        "tools",
        "tool_invocations",
        "approvals",
        "audit_logs",
    }
    for table in tenant_tables:
        assert "organization_id" in columns[table], f"{table} is missing organization_id"


@pytest.mark.asyncio
async def test_sqlite_engine_uses_wal(engine) -> None:
    """SQLite runs in WAL mode with foreign keys enforced (SPEC §4.2)."""
    from sqlalchemy import text

    async with engine.connect() as connection:
        journal = (await connection.execute(text("PRAGMA journal_mode"))).scalar()
        foreign_keys = (await connection.execute(text("PRAGMA foreign_keys"))).scalar()
    assert str(journal).lower() == "wal"
    assert int(foreign_keys) == 1


# --------------------------------------------------------------------------- #
# Public endpoints and §6 Phase 2.1 — authentication
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_health_is_public_and_reports_database(client) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


@pytest.mark.asyncio
async def test_setup_status_then_first_run_setup(client) -> None:
    before = await client.get("/api/auth/setup-status")
    assert before.json() == {"needs_setup": True, "user_count": 0, "organization_count": 0}

    created = await client.post(
        "/api/auth/setup",
        json={
            "email": "owner@nexus.app",
            "password": TEST_PASSWORD,
            "display_name": "Owner",
            "organization_name": "Studio",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "owner@nexus.app"

    after = await client.get("/api/auth/setup-status")
    assert after.json()["needs_setup"] is False

    # A second setup must be refused: no account can be created anonymously later.
    again = await client.post(
        "/api/auth/setup",
        json={
            "email": "attacker@evil.example",
            "password": TEST_PASSWORD,
            "display_name": "Attacker",
            "organization_name": "Evil",
        },
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_password_is_hashed_with_argon2(owner, session_factory) -> None:
    from app.models.identity import User

    async with session_factory() as session:
        user = await session.get(User, owner["user_id"])
    assert user is not None
    assert user.password_hash.startswith("$argon2id$")
    assert TEST_PASSWORD not in user.password_hash


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(client, owner) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"email": "owner@nexus.app", "password": "definitely-wrong"},
    )
    assert response.status_code == 401
    # The error must not reveal whether the account exists.
    assert response.json()["error"]["code"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_login_locks_out_after_repeated_failures(client, owner) -> None:
    for _ in range(5):
        await client.post(
            "/api/auth/login", json={"email": "owner@nexus.app", "password": "wrong-password"}
        )
    locked = await client.post(
        "/api/auth/login",
        json={"email": "owner@nexus.app", "password": TEST_PASSWORD},
    )
    assert locked.status_code == 401
    assert locked.json()["error"]["code"] == "account_locked"


@pytest.mark.asyncio
async def test_refresh_token_rotates_and_detects_replay(client, owner) -> None:
    first = await client.post("/api/auth/refresh", json={"refresh_token": owner["refresh_token"]})
    assert first.status_code == 200, first.text
    rotated = first.json()["refresh_token"]
    assert rotated != owner["refresh_token"]

    replay = await client.post("/api/auth/refresh", json={"refresh_token": owner["refresh_token"]})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "token_revoked"


@pytest.mark.asyncio
async def test_me_returns_role_and_permissions(client, owner) -> None:
    response = await client.get("/api/auth/me", headers=owner["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "owner"
    assert "agents:write" in body["permissions"]
    assert body["organization"]["autonomy_level"] == "3"


# --------------------------------------------------------------------------- #
# Q5 — every protected route rejects anonymous callers with 401
# --------------------------------------------------------------------------- #
PROTECTED_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/agents"),
    ("POST", "/api/agents"),
    ("GET", "/api/agents/agent_x"),
    ("PATCH", "/api/agents/agent_x"),
    ("GET", "/api/agents/agent_x/versions"),
    ("DELETE", "/api/agents/agent_x"),
    ("GET", "/api/runs"),
    ("POST", "/api/runs"),
    ("GET", "/api/runs/run_x"),
    ("POST", "/api/runs/run_x/cancel"),
    ("GET", "/api/runs/run_x/events"),
    ("GET", "/api/events"),
    ("GET", "/api/approvals"),
    ("POST", "/api/approvals/apr_x/decide"),
    ("GET", "/api/tools"),
    ("POST", "/api/tools/invoke"),
    ("GET", "/api/connections"),
    ("POST", "/api/credentials"),
    ("GET", "/api/devices"),
    ("POST", "/api/devices/pair"),
    ("GET", "/api/browser-sessions"),
    ("GET", "/api/adapters"),
    ("GET", "/api/missions"),
    ("POST", "/api/missions"),
    ("GET", "/api/pull-requests"),
    ("GET", "/api/audit"),
    ("GET", "/api/system/autonomy"),
    ("PUT", "/api/system/autonomy"),
    ("GET", "/api/system/dashboard"),
    ("GET", "/api/system/usage"),
    ("POST", "/api/system/action-policy/evaluate"),
    ("POST", "/api/kill-switch"),
    ("GET", "/api/members"),
    ("POST", "/api/members"),
    ("GET", "/api/auth/me"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/password"),
    ("GET", "/api/conversations"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), PROTECTED_ROUTES)
async def test_protected_routes_require_authentication(
    client, owner, method: str, path: str
) -> None:
    """No credentials must yield 401, never 200 and never 500 (AGENTS.md Q5)."""
    response = await client.request(method, path, json={})
    assert response.status_code == 401, f"{method} {path} returned {response.status_code}"
    assert response.json()["error"]["code"] in {
        "unauthenticated",
        "token_expired",
        "invalid_token",
        "wrong_token_type",
    }


@pytest.mark.asyncio
async def test_invalid_bearer_token_is_rejected(client) -> None:
    response = await client.get("/api/agents", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


@pytest.mark.asyncio
async def test_refresh_token_cannot_be_used_as_access_token(client, owner) -> None:
    response = await client.get(
        "/api/agents", headers={"Authorization": f"Bearer {owner['refresh_token']}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "wrong_token_type"


# --------------------------------------------------------------------------- #
# §6 Phase 2.1 — RBAC and tenant isolation
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_viewer_cannot_write_but_can_read(client, viewer, owner) -> None:
    read = await client.get("/api/agents", headers=viewer["headers"])
    assert read.status_code == 200

    write = await client.post(
        "/api/agents", headers=viewer["headers"], json={"name": "Nope", "role": "backend"}
    )
    assert write.status_code == 403
    assert write.json()["error"]["code"] == "forbidden"

    # The owner can do the same write.
    ok = await client.post(
        "/api/agents", headers=owner["headers"], json={"name": "Yes", "role": "backend"}
    )
    assert ok.status_code == 201


@pytest.mark.asyncio
async def test_agent_from_another_organization_is_invisible(
    client, owner, agent, second_tenant
) -> None:
    response = await client.get(f"/api/agents/{agent['id']}", headers=second_tenant["headers"])
    assert response.status_code == 404

    listed = await client.get("/api/agents", headers=second_tenant["headers"])
    assert listed.json()["total"] == 0


@pytest.mark.asyncio
async def test_owner_cannot_be_removed_as_last_owner(client, owner) -> None:
    added = await client.post(
        "/api/members",
        headers=owner["headers"],
        json={
            "email": "member@nexus.app",
            "display_name": "Member",
            "password": VIEWER_PASSWORD,
            "role": "member",
        },
    )
    assert added.status_code == 201, added.text
    assert added.json()["role"] == "member"

    demote_self = await client.patch(
        f"/api/members/{owner['user_id']}", headers=owner["headers"], json={"role": "member"}
    )
    assert demote_self.status_code == 409
    assert demote_self.json()["error"]["code"] == "last_owner"


@pytest.mark.asyncio
async def test_duplicate_member_is_rejected(client, owner) -> None:
    payload = {
        "email": "dup@nexus.app",
        "display_name": "Dup",
        "password": VIEWER_PASSWORD,
        "role": "member",
    }
    assert (
        await client.post("/api/members", headers=owner["headers"], json=payload)
    ).status_code == 201
    again = await client.post("/api/members", headers=owner["headers"], json=payload)
    assert again.status_code == 409


# --------------------------------------------------------------------------- #
# §6 Phase 2.5 — agents and immutable versions
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_agent_create_makes_version_one(client, owner) -> None:
    created = await client.post(
        "/api/agents",
        headers=owner["headers"],
        json={
            "name": "Backend Engineer",
            "slug": "backend-engineer",
            "role": "backend",
            "goal": "Ship it",
            "instructions": "Read docs/SPEC.md",
            "tools": ["calc.evaluate"],
        },
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    assert agent["current_version"] == 1
    assert agent["slug"] == "backend-engineer"

    versions = await client.get(f"/api/agents/{agent['id']}/versions", headers=owner["headers"])
    assert versions.status_code == 200
    rows = versions.json()
    assert len(rows) == 1
    assert rows[0]["version"] == 1
    assert rows[0]["instructions"] == "Read docs/SPEC.md"


@pytest.mark.asyncio
async def test_agent_update_appends_immutable_version(client, owner, agent) -> None:
    updated = await client.patch(
        f"/api/agents/{agent['id']}",
        headers=owner["headers"],
        json={"instructions": "Now with tests", "change_note": "tighten instructions"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["current_version"] == 2

    versions = (
        await client.get(f"/api/agents/{agent['id']}/versions", headers=owner["headers"])
    ).json()
    assert [row["version"] for row in versions] == [2, 1]
    by_version = {row["version"]: row for row in versions}
    # Version 1 is untouched: versions are immutable snapshots.
    assert by_version[1]["instructions"] == "Follow docs/SPEC.md"
    assert by_version[2]["instructions"] == "Now with tests"
    assert by_version[2]["change_note"] == "tighten instructions"

    diff = await client.get(
        f"/api/agents/{agent['id']}/versions/1/diff/2", headers=owner["headers"]
    )
    assert diff.status_code == 200
    assert "instructions" in diff.json()["changed_fields"]


@pytest.mark.asyncio
async def test_agent_clone_and_enable_toggle(client, owner, agent) -> None:
    cloned = await client.post(
        f"/api/agents/{agent['id']}/clone", headers=owner["headers"], params={"name": "Copy"}
    )
    assert cloned.status_code == 201, cloned.text
    assert cloned.json()["name"] == "Copy"
    assert cloned.json()["id"] != agent["id"]

    disabled = await client.post(
        f"/api/agents/{agent['id']}/enable", headers=owner["headers"], params={"enabled": "false"}
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_enabled"] is False


@pytest.mark.asyncio
async def test_disabled_agent_cannot_start_a_run(client, owner, agent) -> None:
    await client.post(
        f"/api/agents/{agent['id']}/enable", headers=owner["headers"], params={"enabled": "false"}
    )
    response = await client.post(
        "/api/runs", headers=owner["headers"], json={"agent_id": agent["id"], "directive": "go"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agent_disabled"


@pytest.mark.asyncio
async def test_agent_slug_conflict_returns_409(client, owner, agent) -> None:
    response = await client.post(
        "/api/agents",
        headers=owner["headers"],
        json={"name": "Another", "slug": agent["slug"], "role": "backend"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_invalid_avatar_colour_is_rejected(client, owner) -> None:
    response = await client.post(
        "/api/agents",
        headers=owner["headers"],
        json={"name": "Bad", "role": "backend", "avatar_color": "red"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


# --------------------------------------------------------------------------- #
# §7 — runs and the authoritative event log
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_run_lifecycle_emits_monotonic_events(client, owner, agent) -> None:
    created = await client.post(
        "/api/runs", headers=owner["headers"], json={"agent_id": agent["id"], "directive": "build"}
    )
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["status"] == "created"

    started = await client.post(f"/api/runs/{run['id']}/start", headers=owner["headers"])
    assert started.status_code == 200
    assert started.json()["status"] == "running"

    completed = await client.post(f"/api/runs/{run['id']}/complete", headers=owner["headers"])
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["finished_at"] is not None

    events = (await client.get(f"/api/runs/{run['id']}/events", headers=owner["headers"])).json()
    types = [event["event_type"] for event in events]
    assert types == ["run.created", "run.started", "run.completed"]
    sequences = [event["sequence"] for event in events]
    assert sequences == sorted(sequences)
    assert sequences == [1, 2, 3]

    replay = await client.get(
        f"/api/runs/{run['id']}/events",
        headers=owner["headers"],
        params={"after_sequence": 2},
    )
    assert [event["event_type"] for event in replay.json()] == ["run.completed"]


@pytest.mark.asyncio
async def test_run_idempotency_key_prevents_duplicate_work(client, owner, agent) -> None:
    payload = {"agent_id": agent["id"], "directive": "once", "idempotency_key": "mission-42"}
    first = await client.post("/api/runs", headers=owner["headers"], json=payload)
    second = await client.post("/api/runs", headers=owner["headers"], json=payload)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    listed = await client.get("/api/runs", headers=owner["headers"])
    assert listed.json()["total"] == 1


@pytest.mark.asyncio
async def test_illegal_run_transition_is_rejected(client, owner, agent) -> None:
    run = (
        await client.post(
            "/api/runs", headers=owner["headers"], json={"agent_id": agent["id"], "directive": "x"}
        )
    ).json()
    # created -> completed is not a legal transition.
    response = await client.post(f"/api/runs/{run['id']}/complete", headers=owner["headers"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "illegal_transition"


@pytest.mark.asyncio
async def test_run_cancel_and_terminal_state_is_final(client, owner, agent) -> None:
    run = (
        await client.post(
            "/api/runs", headers=owner["headers"], json={"agent_id": agent["id"], "directive": "x"}
        )
    ).json()
    cancelled = await client.post(f"/api/runs/{run['id']}/cancel", headers=owner["headers"])
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    again = await client.post(f"/api/runs/{run['id']}/start", headers=owner["headers"])
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_checkpoint_and_resume(client, owner, agent) -> None:
    run = (
        await client.post(
            "/api/runs", headers=owner["headers"], json={"agent_id": agent["id"], "directive": "x"}
        )
    ).json()
    await client.post(f"/api/runs/{run['id']}/start", headers=owner["headers"])
    paused = await client.post(f"/api/runs/{run['id']}/pause", headers=owner["headers"])
    assert paused.json()["status"] == "paused"

    checkpoint = await client.post(
        f"/api/runs/{run['id']}/checkpoints",
        headers=owner["headers"],
        params={"step": 3, "label": "after plan"},
    )
    assert checkpoint.status_code == 201, checkpoint.text
    assert checkpoint.json()["step"] == 3

    resumed = await client.post(f"/api/runs/{run['id']}/resume", headers=owner["headers"])
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "running"

    detail = await client.get(f"/api/runs/{run['id']}", headers=owner["headers"])
    assert detail.json()["latest_checkpoint_step"] == 3


@pytest.mark.asyncio
async def test_unknown_event_type_is_never_stored(session_factory, owner) -> None:
    from app.core.errors import ValidationFailedError
    from app.services import event_service

    async with session_factory() as session:
        with pytest.raises(ValidationFailedError):
            await event_service.append_event(
                session,
                organization_id=owner["organization_id"],
                event_type="totally.made.up",
            )


# --------------------------------------------------------------------------- #
# §6 Phase 2.7 — Tool Gateway
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_builtin_tools_are_registered_with_json_schema(client, owner) -> None:
    synced = await client.post("/api/tools/sync-builtin", headers=owner["headers"])
    assert synced.status_code == 200, synced.text
    slugs = {tool["slug"] for tool in synced.json()}
    assert {"http.get", "calc.evaluate", "time.now", "knowledge.search"} <= slugs
    calc = next(tool for tool in synced.json() if tool["slug"] == "calc.evaluate")
    assert calc["input_schema"]["required"] == ["expression"]


@pytest.mark.asyncio
async def test_tool_invocation_succeeds_and_is_audited(client, owner) -> None:
    await client.post("/api/tools/sync-builtin", headers=owner["headers"])
    response = await client.post(
        "/api/tools/invoke",
        headers=owner["headers"],
        json={"tool_slug": "calc.evaluate", "arguments": {"expression": "(2 + 3) * 4"}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"] == "allow"
    assert body["outcome"] == "success"
    assert body["result"] == {"value": 20}

    audit = await client.get(
        "/api/audit", headers=owner["headers"], params={"action": "tools.invoke"}
    )
    assert audit.status_code == 200
    assert len(audit.json()) == 1


@pytest.mark.asyncio
async def test_tool_argument_schema_is_enforced(client, owner) -> None:
    await client.post("/api/tools/sync-builtin", headers=owner["headers"])
    response = await client.post(
        "/api/tools/invoke",
        headers=owner["headers"],
        json={"tool_slug": "calc.evaluate", "arguments": {}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_tool_arguments"


@pytest.mark.asyncio
async def test_calculator_rejects_code_injection(client, owner) -> None:
    await client.post("/api/tools/sync-builtin", headers=owner["headers"])
    response = await client.post(
        "/api/tools/invoke",
        headers=owner["headers"],
        json={
            "tool_slug": "calc.evaluate",
            "arguments": {"expression": "__import__('os').system('id')"},
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_expression"


@pytest.mark.asyncio
async def test_agent_tool_allowlist_is_enforced(client, owner) -> None:
    await client.post("/api/tools/sync-builtin", headers=owner["headers"])
    created = await client.post(
        "/api/agents",
        headers=owner["headers"],
        json={"name": "Restricted", "role": "backend", "tools": ["time.now"]},
    )
    agent = created.json()

    denied = await client.post(
        "/api/tools/invoke",
        headers=owner["headers"],
        json={
            "tool_slug": "calc.evaluate",
            "arguments": {"expression": "1+1"},
            "agent_id": agent["id"],
        },
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "tool_not_allowed"

    allowed = await client.post(
        "/api/tools/invoke",
        headers=owner["headers"],
        json={"tool_slug": "time.now", "arguments": {}, "agent_id": agent["id"]},
    )
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_knowledge_search_is_honestly_not_configured(client, owner) -> None:
    await client.post("/api/tools/sync-builtin", headers=owner["headers"])
    response = await client.post(
        "/api/tools/invoke",
        headers=owner["headers"],
        json={"tool_slug": "knowledge.search", "arguments": {"query": "anything"}},
    )
    assert response.json()["result"]["configured"] is False


@pytest.mark.asyncio
async def test_http_get_blocks_hosts_outside_the_allowlist(client, owner) -> None:
    await client.post("/api/tools/sync-builtin", headers=owner["headers"])
    blocked = await client.post(
        "/api/tools/invoke",
        headers=owner["headers"],
        json={"tool_slug": "http.get", "arguments": {"url": "https://example.com/secret"}},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "host_not_allowed"


# --------------------------------------------------------------------------- #
# §13 — action policy, approvals and the kill switch
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_level_zero_policy_asks_for_every_call(client, owner) -> None:
    await client.post("/api/tools/sync-builtin", headers=owner["headers"])
    await client.put("/api/system/autonomy", headers=owner["headers"], json={"level": "0"})

    result = await client.post(
        "/api/tools/invoke",
        headers=owner["headers"],
        json={"tool_slug": "calc.evaluate", "arguments": {"expression": "1+1"}},
    )
    assert result.status_code == 200
    body = result.json()
    assert body["decision"] == "ask"
    assert body["outcome"] == "awaiting_approval"
    assert body["approval_id"]

    approvals = await client.get("/api/approvals", headers=owner["headers"])
    assert approvals.json()["total"] == 1


@pytest.mark.asyncio
async def test_full_auto_allows_but_keeps_irreversible_actions_on_ask(client, owner) -> None:
    evaluate = await client.post(
        "/api/system/action-policy/evaluate",
        headers=owner["headers"],
        json={"tool": "fs.delete_outside_workspace"},
    )
    assert evaluate.json()["decision"] == "ask"

    allowed = await client.post(
        "/api/system/action-policy/evaluate",
        headers=owner["headers"],
        json={"tool": "calc.evaluate"},
    )
    assert allowed.json()["decision"] == "allow"


@pytest.mark.asyncio
async def test_action_policy_rejects_inert_rules(client, owner) -> None:
    response = await client.put(
        "/api/system/action-policy",
        headers=owner["headers"],
        json=[{"decision": "allow"}],
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_policy_rule"


@pytest.mark.asyncio
async def test_action_policy_first_match_wins(client, owner) -> None:
    rules = [
        {"decision": "deny", "tool": "http.get"},
        {"decision": "allow", "match_all": True},
    ]
    written = await client.put("/api/system/action-policy", headers=owner["headers"], json=rules)
    assert written.status_code == 200, written.text

    denied = await client.post(
        "/api/system/action-policy/evaluate", headers=owner["headers"], json={"tool": "http.get"}
    )
    assert denied.json()["decision"] == "deny"
    assert denied.json()["matched_rule"] == 0


@pytest.mark.asyncio
async def test_approval_decide_is_audited_and_final(client, owner) -> None:
    await client.post("/api/tools/sync-builtin", headers=owner["headers"])
    await client.put("/api/system/autonomy", headers=owner["headers"], json={"level": "0"})
    invocation = await client.post(
        "/api/tools/invoke",
        headers=owner["headers"],
        json={"tool_slug": "calc.evaluate", "arguments": {"expression": "2+2"}},
    )
    approval_id = invocation.json()["approval_id"]

    decided = await client.post(
        f"/api/approvals/{approval_id}/decide",
        headers=owner["headers"],
        json={"approve": True, "note": "fine"},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"
    assert decided.json()["decided_by"] == owner["user_id"]

    again = await client.post(
        f"/api/approvals/{approval_id}/decide",
        headers=owner["headers"],
        json={"approve": False},
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_viewer_cannot_decide_approvals(client, viewer, owner) -> None:
    await client.post("/api/tools/sync-builtin", headers=owner["headers"])
    await client.put("/api/system/autonomy", headers=owner["headers"], json={"level": "0"})
    invocation = await client.post(
        "/api/tools/invoke",
        headers=owner["headers"],
        json={"tool_slug": "calc.evaluate", "arguments": {"expression": "2+2"}},
    )
    approval_id = invocation.json()["approval_id"]
    denied = await client.post(
        f"/api/approvals/{approval_id}/decide", headers=viewer["headers"], json={"approve": True}
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_emergency_stop_blocks_new_work_until_cleared(client, owner, agent) -> None:
    engaged = await client.post(
        "/api/kill-switch", headers=owner["headers"], json={"engage": True, "reason": "test"}
    )
    assert engaged.status_code == 200
    assert engaged.json()["engaged"] is True

    blocked = await client.post(
        "/api/runs", headers=owner["headers"], json={"agent_id": agent["id"], "directive": "go"}
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "emergency_stop_engaged"

    events = await client.get(
        "/api/events", headers=owner["headers"], params={"event_type": "emergency_stop.engaged"}
    )
    assert len(events.json()) == 1

    cleared = await client.post(
        "/api/kill-switch", headers=owner["headers"], json={"engage": False}
    )
    assert cleared.json()["engaged"] is False
    allowed = await client.post(
        "/api/runs", headers=owner["headers"], json={"agent_id": agent["id"], "directive": "go"}
    )
    assert allowed.status_code == 201


@pytest.mark.asyncio
async def test_kill_switch_requires_system_permission(client, viewer, owner) -> None:
    await client.post("/api/kill-switch", headers=owner["headers"], json={"engage": True})
    response = await client.post(
        "/api/kill-switch", headers=viewer["headers"], json={"engage": False}
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# §3.1/§3.2 — connections, terms, pairing, adapters, secrets
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_browser_connection_requires_terms_acknowledgement(client, owner) -> None:
    await client.post("/api/providers/sync-defaults", headers=owner["headers"])
    created = await client.post(
        "/api/connections",
        headers=owner["headers"],
        json={"name": "Mock tab", "provider_slug": "mock", "kind": "browser_session"},
    )
    assert created.status_code == 201, created.text
    connection = created.json()
    assert connection["terms_acknowledged"] is False
    assert connection["capabilities"]["usage_reporting"] == "unsupported"

    blocked = await client.patch(
        f"/api/connections/{connection['id']}", headers=owner["headers"], json={"status": "enabled"}
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "terms_not_acknowledged"

    ack = await client.post(
        f"/api/connections/{connection['id']}/terms-acknowledgement", headers=owner["headers"]
    )
    assert ack.status_code == 200
    assert ack.json()["acknowledged"] is True
    assert ack.json()["acknowledged_by"] == owner["user_id"]

    enabled = await client.patch(
        f"/api/connections/{connection['id']}", headers=owner["headers"], json={"status": "enabled"}
    )
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "enabled"


@pytest.mark.asyncio
async def test_api_provider_is_disabled_by_default(client, owner) -> None:
    await client.post("/api/providers/sync-defaults", headers=owner["headers"])
    providers = (await client.get("/api/providers", headers=owner["headers"])).json()
    by_slug = {row["slug"]: row for row in providers}
    assert by_slug["openai_compatible"]["enabled"] is False
    assert by_slug["ollama"]["enabled"] is True

    response = await client.post(
        "/api/connections",
        headers=owner["headers"],
        json={"name": "OpenAI", "provider_slug": "openai_compatible", "kind": "api"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "provider_disabled"


@pytest.mark.asyncio
async def test_credential_is_encrypted_and_never_returned(client, owner, session_factory) -> None:
    from app.models.connections import Credential

    secret_value = "sk-live-abcdef0123456789"
    created = await client.post(
        "/api/credentials",
        headers=owner["headers"],
        json={"name": "OpenAI key", "kind": "api_key", "value": secret_value},
    )
    assert created.status_code == 201, created.text
    assert secret_value not in created.text
    assert "ciphertext" not in created.text

    listed = await client.get("/api/credentials", headers=owner["headers"])
    assert secret_value not in listed.text

    async with session_factory() as session:
        row = await session.get(Credential, created.json()["id"])
        assert row is not None
        assert secret_value not in row.ciphertext
        assert row.ciphertext.startswith("fernet:")


@pytest.mark.asyncio
async def test_raw_credential_refs_are_rejected() -> None:
    from app.core.errors import ValidationFailedError
    from app.core.security import validate_credential_ref

    assert validate_credential_ref("env:OPENAI_API_KEY") == "env:OPENAI_API_KEY"
    with pytest.raises(ValidationFailedError):
        validate_credential_ref("sk-live-raw-key")


@pytest.mark.asyncio
async def test_device_pairing_returns_credential_once_and_revoke_is_immediate(
    client, owner, session_factory
) -> None:
    from app.models.connections import BrowserDevice

    paired = await client.post(
        "/api/devices/pair",
        headers=owner["headers"],
        json={"label": "Chrome — work", "userscript_version": "1.0.0"},
    )
    assert paired.status_code == 201, paired.text
    credential = paired.json()["credential"]
    device_id = paired.json()["device_id"]

    listed = await client.get("/api/devices", headers=owner["headers"])
    assert credential not in listed.text
    assert "credential_hash" not in listed.text

    async with session_factory() as session:
        device = await session.get(BrowserDevice, device_id)
        assert device is not None
        assert device.credential_hash != credential
        hash_before = device.credential_hash

    revoked = await client.post(f"/api/devices/{device_id}/revoke", headers=owner["headers"])
    assert revoked.status_code == 200

    async with session_factory() as session:
        device = await session.get(BrowserDevice, device_id)
        assert device is not None
        assert device.revoked_at is not None
        assert device.credential_hash != hash_before


@pytest.mark.asyncio
async def test_revoked_device_cannot_register_tabs(client, owner) -> None:
    paired = await client.post(
        "/api/devices/pair",
        headers=owner["headers"],
        json={"label": "Chrome", "userscript_version": "1.0.0"},
    )
    device_id = paired.json()["device_id"]
    await client.post(f"/api/devices/{device_id}/revoke", headers=owner["headers"])
    response = await client.post(
        f"/api/devices/{device_id}/tabs",
        headers=owner["headers"],
        params={"provider_slug": "mock"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "device_revoked"


@pytest.mark.asyncio
async def test_tab_grant_and_waiting_for_user_event(client, owner, agent) -> None:
    paired = await client.post(
        "/api/devices/pair",
        headers=owner["headers"],
        json={"label": "Chrome", "userscript_version": "1.0.0"},
    )
    device_id = paired.json()["device_id"]
    tab = await client.post(
        f"/api/devices/{device_id}/tabs",
        headers=owner["headers"],
        params={"provider_slug": "mock", "url": "https://mock.local/chat"},
    )
    assert tab.status_code == 201, tab.text
    tab_id = tab.json()["id"]

    granted = await client.post(
        f"/api/browser-sessions/{tab_id}/grant",
        headers=owner["headers"],
        json={"agent_id": agent["id"]},
    )
    assert granted.status_code == 200
    assert granted.json()["granted_agent_id"] == agent["id"]

    updated = await client.patch(
        f"/api/browser-sessions/{tab_id}",
        headers=owner["headers"],
        json={"state": "WAITING_FOR_USER"},
    )
    assert updated.status_code == 200
    assert updated.json()["state"] == "WAITING_FOR_USER"

    events = await client.get(
        "/api/events",
        headers=owner["headers"],
        params={"event_type": "browser.waiting_for_user"},
    )
    assert len(events.json()) == 1


VALID_ADAPTER_YAML = """
id: mock
version: 1
display_name: Mock provider
selectors:
  input: "textarea#prompt"
  send: "button#send"
  reply: "div#reply"
  generating_indicator: "div.generating"
completion:
  indicator_disappears: true
  stable_ms: 750
  hard_timeout_ms: 120000
capabilities:
  streaming: supported
  agent_mode: supported
"""


@pytest.mark.asyncio
async def test_adapter_versions_are_validated_and_rollback_works(client, owner) -> None:
    first = await client.post(
        "/api/adapters",
        headers=owner["headers"],
        json={"provider_slug": "mock", "yaml_body": VALID_ADAPTER_YAML},
    )
    assert first.status_code == 201, first.text
    assert first.json()["version"] == 1

    second = await client.post(
        "/api/adapters",
        headers=owner["headers"],
        json={
            "provider_slug": "mock",
            "yaml_body": VALID_ADAPTER_YAML.replace("button#send", "button.send-v2"),
        },
    )
    assert second.status_code == 201
    assert second.json()["version"] == 2

    versions = (await client.get("/api/adapters", headers=owner["headers"])).json()
    active = [row for row in versions if row["is_active"]]
    assert len(active) == 1
    assert active[0]["version"] == 2

    rolled = await client.post(
        f"/api/adapters/{first.json()['id']}/rollback", headers=owner["headers"]
    )
    assert rolled.status_code == 200
    assert rolled.json()["version"] == 1


@pytest.mark.asyncio
async def test_invalid_adapter_yaml_is_rejected(client, owner) -> None:
    response = await client.post(
        "/api/adapters",
        headers=owner["headers"],
        json={"provider_slug": "mock", "yaml_body": "id: broken\nversion: 1\n"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_adapter_yaml"

    not_yaml = await client.post(
        "/api/adapters",
        headers=owner["headers"],
        json={"provider_slug": "mock", "yaml_body": "just a string"},
    )
    assert not_yaml.status_code == 422


@pytest.mark.asyncio
async def test_selector_test_never_claims_an_unchecked_pass(client, owner) -> None:
    response = await client.post(
        "/api/adapters/selector-test",
        headers=owner["headers"],
        json={"yaml_body": VALID_ADAPTER_YAML},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["valid"] is True
    assert body["errors"] and "live page not checked" in body["errors"][0]


# --------------------------------------------------------------------------- #
# §1 / §6 Phase 3 — missions, DAG and timeline
# --------------------------------------------------------------------------- #
MISSION_PAYLOAD = {
    "title": "Ship the landing page",
    "directive": "Build and deploy the marketing page",
    "acceptance_criteria": ["page renders in AR and EN"],
    "assumptions": ["brand colours already approved"],
    "tasks": [
        {"key": "api", "title": "Build the API", "specialty": "backend"},
        {
            "key": "ui",
            "title": "Build the UI",
            "specialty": "frontend",
            "depends_on": ["api"],
        },
    ],
}


@pytest.mark.asyncio
async def test_mission_creation_validates_the_dag(client, owner) -> None:
    created = await client.post("/api/missions", headers=owner["headers"], json=MISSION_PAYLOAD)
    assert created.status_code == 201, created.text
    mission = created.json()
    assert mission["plan_validation"]["valid"] is True
    assert mission["plan_validation"]["warnings"], "frontend+backend without a contract must warn"

    tasks = await client.get(f"/api/missions/{mission['id']}/tasks", headers=owner["headers"])
    assert len(tasks.json()) == 2


@pytest.mark.asyncio
async def test_mission_with_a_cyclic_dag_is_rejected(client, owner) -> None:
    payload = {
        "title": "Cyclic",
        "directive": "x",
        "tasks": [
            {"key": "a", "title": "A", "depends_on": ["b"]},
            {"key": "b", "title": "B", "depends_on": ["a"]},
        ],
    }
    response = await client.post("/api/missions", headers=owner["headers"], json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "dag_cycle"


@pytest.mark.asyncio
async def test_task_claim_respects_dependencies_and_is_atomic(client, owner) -> None:
    mission = (
        await client.post("/api/missions", headers=owner["headers"], json=MISSION_PAYLOAD)
    ).json()
    tasks = (
        await client.get(f"/api/missions/{mission['id']}/tasks", headers=owner["headers"])
    ).json()
    by_title = {task["title"]: task for task in tasks}
    ui_task = by_title["Build the UI"]
    api_task = by_title["Build the API"]

    blocked = await client.post(
        f"/api/missions/tasks/{ui_task['id']}/claim", headers=owner["headers"]
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "dependencies_unfinished"

    claimed = await client.post(
        f"/api/missions/tasks/{api_task['id']}/claim", headers=owner["headers"]
    )
    assert claimed.status_code == 200
    assert claimed.json()["status"] == "running"

    twice = await client.post(
        f"/api/missions/tasks/{api_task['id']}/claim", headers=owner["headers"]
    )
    assert twice.status_code == 409

    await client.post(f"/api/missions/tasks/{api_task['id']}/complete", headers=owner["headers"])
    unblocked = await client.post(
        f"/api/missions/tasks/{ui_task['id']}/claim", headers=owner["headers"]
    )
    assert unblocked.status_code == 200


@pytest.mark.asyncio
async def test_mission_timeline_has_the_eight_computed_steps(client, owner) -> None:
    mission = (
        await client.post("/api/missions", headers=owner["headers"], json=MISSION_PAYLOAD)
    ).json()
    timeline = await client.get(f"/api/missions/{mission['id']}/timeline", headers=owner["headers"])
    assert timeline.status_code == 200, timeline.text
    body = timeline.json()
    assert [step["step"] for step in body["steps"]] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert [step["key"] for step in body["steps"]] == [
        "request",
        "analyze",
        "distribute",
        "execute",
        "collect",
        "pull_request",
        "review_merge",
        "completed",
    ]
    assert body["tasks_total"] == 2
    assert body["steps"][0]["state"] == "done"
    assert body["steps"][1]["state"] == "done"
    assert body["steps"][7]["state"] == "pending"


@pytest.mark.asyncio
async def test_merge_requires_a_human_approval_and_green_checks(client, owner) -> None:
    pull_request = await client.post(
        "/api/pull-requests",
        headers=owner["headers"],
        json={
            "repository": "oldman-088/multi-agent-project",
            "title": "[AATM-test] backend slice",
            "branch": "arena/test",
        },
    )
    assert pull_request.status_code == 201, pull_request.text
    pr = pull_request.json()

    missing = await client.post(
        f"/api/pull-requests/{pr['id']}/merge",
        headers=owner["headers"],
        params={"approval_id": "apr_none"},
    )
    assert missing.status_code == 404

    review = await client.post(
        f"/api/pull-requests/{pr['id']}/reviews",
        headers=owner["headers"],
        json={"verdict": "comment", "summary": "AI review only"},
    )
    assert review.status_code == 201
    # An AI review never sets human approval.
    assert review.json()["human_approved_by"] is None


@pytest.mark.asyncio
async def test_ai_review_verdict_is_validated(client, owner) -> None:
    pr = (
        await client.post(
            "/api/pull-requests",
            headers=owner["headers"],
            json={"repository": "o/r", "branch": "b"},
        )
    ).json()
    response = await client.post(
        f"/api/pull-requests/{pr['id']}/reviews",
        headers=owner["headers"],
        json={"verdict": "LGTM", "summary": "x"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


# --------------------------------------------------------------------------- #
# §8.3-H — dashboard counts and §3.3 honesty
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_dashboard_counts_are_real(client, owner, agent) -> None:
    await client.post(
        "/api/runs", headers=owner["headers"], json={"agent_id": agent["id"], "directive": "one"}
    )
    dashboard = (await client.get("/api/system/dashboard", headers=owner["headers"])).json()
    assert dashboard["agents_total"] == 1
    assert dashboard["agents_enabled"] == 1
    assert dashboard["runs_total"] == 1
    assert dashboard["approvals_pending"] == 0
    assert dashboard["autonomy_level"] == "3"


@pytest.mark.asyncio
async def test_usage_is_null_rather_than_invented(client, owner) -> None:
    usage = (await client.get("/api/system/usage", headers=owner["headers"])).json()
    assert usage["tokens"] is None
    assert usage["cost"] is None
    assert usage["connections_reporting_usage"] == 0


@pytest.mark.asyncio
async def test_first_term_message_reports_null_usage(client, owner, agent) -> None:
    conversation = await client.post(
        "/api/conversations",
        headers=owner["headers"],
        json={"agent_id": agent["id"], "title": "First chat"},
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]

    appended = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        headers=owner["headers"],
        json={"content": "مرحبا، ابدأ العمل"},
    )
    assert appended.status_code == 201, appended.text
    assert appended.json()["usage"] is None

    messages = await client.get(
        f"/api/conversations/{conversation_id}/messages", headers=owner["headers"]
    )
    assert [row["role"] for row in messages.json()] == ["user"]


# --------------------------------------------------------------------------- #
# §3.2 — safety helpers
# --------------------------------------------------------------------------- #
def test_secrets_are_redacted_in_log_payloads() -> None:
    from app.core.logging import redact

    cleaned = redact(
        {
            "email": "owner@nexus.app",
            "password": "hunter2",
            "nested": {"api_key": "sk-live", "note": "ok"},
            "items": [{"refresh_token": "abc"}],
        }
    )
    assert cleaned["email"] == "owner@nexus.app"
    assert cleaned["password"] == "***redacted***"
    assert cleaned["nested"]["api_key"] == "***redacted***"
    assert cleaned["nested"]["note"] == "ok"
    assert cleaned["items"][0]["refresh_token"] == "***redacted***"


def test_bridge_host_must_be_loopback() -> None:
    from app.core.config import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(bridge_host="0.0.0.0")
    assert Settings(bridge_host="127.0.0.1").bridge_host == "127.0.0.1"


def test_password_hash_verification() -> None:
    from app.core.security import hash_password, needs_rehash, verify_password

    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("anything", "not-a-hash")
    assert needs_rehash("not-a-hash") is True


def test_audit_schema_matches_spec_contract() -> None:
    """docs/API.md must document every route the app exposes."""
    import re
    from pathlib import Path

    from app.main import create_app

    # apps/backend/tests -> apps/backend -> apps -> repository root (docs/API.md).
    spec_path = Path(__file__).resolve().parents[3] / "docs" / "API.md"
    assert spec_path.exists(), "docs/API.md must exist (owner: Worker 1 — Backend)"

    from app.core.config import Settings

    app = create_app(Settings(jwt_secret="x" * 40, database_url="sqlite+aiosqlite:///:memory:"))
    schema_paths = set(app.openapi()["paths"])
    documented = set(re.findall(r"`?(/api/[A-Za-z0-9_{}/\-]+)`?", spec_path.read_text()))

    undocumented = sorted(
        path for path in schema_paths if path.startswith("/api/") and path not in documented
    )
    assert not undocumented, f"undocumented API routes in docs/API.md: {undocumented}"
