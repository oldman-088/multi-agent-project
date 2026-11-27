"""REST contract tests for the run, event and approval routes (docs/API.md §5).

Scope: authentication (AGENTS.md Q5), the legal-transition table, tenant
isolation, the per-run monotonic event cursor with replay, exactly-once approval
decisions, and the SPEC §7 event envelope of ``app/api/routes/runs.py``.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.asyncio

RUN_ROUTES: list[tuple[str, str, dict | None]] = [
    ("POST", "/api/runs", {"agent_id": "agt_x", "directive": "d"}),
    ("GET", "/api/runs", None),
    ("GET", "/api/runs/run_x", None),
    ("POST", "/api/runs/run_x/start", None),
    ("POST", "/api/runs/run_x/pause", None),
    ("POST", "/api/runs/run_x/resume", None),
    ("POST", "/api/runs/run_x/cancel", None),
    ("POST", "/api/runs/run_x/complete", None),
    ("POST", "/api/runs/run_x/checkpoints?step=1", {"state": {}}),
    ("GET", "/api/runs/run_x/events", None),
    ("GET", "/api/runs/run_x/events?after_sequence=0", None),
    ("GET", "/api/events", None),
    ("GET", "/api/events?run_id=run_x&after_sequence=1", None),
    ("GET", "/api/approvals", None),
    ("POST", "/api/approvals/apr_x/decide", {"approve": True}),
]

#: SPEC §7 / docs/API.md §5.1: the exact envelope keys, in the documented order.
EVENT_KEYS = [
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


async def _create_run(client, owner, agent, directive: str = "build") -> dict:
    response = await client.post(
        "/api/runs",
        headers=owner["headers"],
        json={"agent_id": agent["id"], "directive": directive},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _run_with_events(client, owner, agent) -> dict:
    """created -> running -> completed, which persists three events."""
    run = await _create_run(client, owner, agent)
    assert (
        await client.post(f"/api/runs/{run['id']}/start", headers=owner["headers"])
    ).status_code == 200
    assert (
        await client.post(f"/api/runs/{run['id']}/complete", headers=owner["headers"])
    ).status_code == 200
    return run


# --------------------------------------------------------------------------- #
# Authentication and authorization
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path", "body"), RUN_ROUTES)
async def test_run_routes_require_credentials(
    client, owner, method: str, path: str, body: dict | None
) -> None:
    response = await client.request(method, path, json=body)
    assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
    assert response.json()["error"]["code"] in {
        "unauthenticated",
        "invalid_token",
        "token_expired",
        "wrong_token_type",
    }


async def test_cancel_requires_the_cancel_permission(client, viewer, owner, agent) -> None:
    """``runs:cancel`` belongs to admin+; a viewer gets 403, not 404 or 500."""
    run = await _create_run(client, owner, agent)
    response = await client.post(f"/api/runs/{run['id']}/cancel", headers=viewer["headers"])
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_viewer_may_read_runs_and_events(client, viewer, owner, agent) -> None:
    run = await _run_with_events(client, owner, agent)
    assert (await client.get("/api/runs", headers=viewer["headers"])).status_code == 200
    assert (
        await client.get(f"/api/runs/{run['id']}", headers=viewer["headers"])
    ).status_code == 200
    assert (
        await client.get(f"/api/runs/{run['id']}/events", headers=viewer["headers"])
    ).status_code == 200
    assert (await client.get("/api/events", headers=viewer["headers"])).status_code == 200


# --------------------------------------------------------------------------- #
# Tenant isolation
# --------------------------------------------------------------------------- #
async def test_runs_and_events_are_invisible_to_another_organization(
    client, owner, agent, second_tenant
) -> None:
    run = await _run_with_events(client, owner, agent)
    headers = second_tenant["headers"]

    for path in (
        f"/api/runs/{run['id']}",
        f"/api/runs/{run['id']}/events",
        f"/api/events?run_id={run['id']}",
    ):
        response = await client.get(path, headers=headers)
        assert response.status_code == 404, f"{path} leaked -> {response.status_code}"

    # The event feed of the other organization is empty, not a 403 and not a leak.
    feed = await client.get("/api/events", headers=headers)
    assert feed.status_code == 200
    assert feed.json() == []

    listed = await client.get("/api/runs", headers=headers)
    assert listed.json()["total"] == 0


async def test_another_organization_cannot_mutate_a_run(
    client, owner, agent, second_tenant
) -> None:
    run = await _create_run(client, owner, agent)
    headers = second_tenant["headers"]
    for path in ("start", "pause", "cancel", "complete"):
        response = await client.post(f"/api/runs/{run['id']}/{path}", headers=headers)
        assert response.status_code == 404, f"{path} -> {response.status_code}"

    still_created = await client.get(f"/api/runs/{run['id']}", headers=owner["headers"])
    assert still_created.json()["status"] == "created"


async def test_another_organization_cannot_create_a_run_for_a_foreign_agent(
    client, agent, second_tenant
) -> None:
    response = await client.post(
        "/api/runs",
        headers=second_tenant["headers"],
        json={"agent_id": agent["id"], "directive": "steal"},
    )
    assert response.status_code == 404


async def test_another_organization_cannot_decide_an_approval(client, owner, agent, second_tenant):
    await client.post("/api/tools/sync-builtin", headers=owner["headers"])
    await client.put("/api/system/autonomy", headers=owner["headers"], json={"level": "0"})
    invoked = await client.post(
        "/api/tools/invoke",
        headers=owner["headers"],
        json={"tool_slug": "calc.evaluate", "arguments": {"expression": "1+1"}},
    )
    assert invoked.status_code == 200, invoked.text
    approval_id = invoked.json()["approval_id"]
    assert approval_id

    response = await client.post(
        f"/api/approvals/{approval_id}/decide",
        headers=second_tenant["headers"],
        json={"approve": True},
    )
    assert response.status_code == 404

    # It is still pending for its real organization.
    table = await client.get(
        "/api/approvals", headers=owner["headers"], params={"status": "pending"}
    )
    assert table.json()["total"] == 1


async def test_approvals_list_is_scoped_to_the_organization(client, owner, second_tenant):
    await client.post("/api/tools/sync-builtin", headers=owner["headers"])
    await client.put("/api/system/autonomy", headers=owner["headers"], json={"level": "0"})
    await client.post(
        "/api/tools/invoke",
        headers=owner["headers"],
        json={"tool_slug": "calc.evaluate", "arguments": {"expression": "2+2"}},
    )
    owner_view = await client.get("/api/approvals", headers=owner["headers"])
    assert owner_view.json()["total"] == 1
    other_view = await client.get("/api/approvals", headers=second_tenant["headers"])
    assert other_view.json()["total"] == 0


# --------------------------------------------------------------------------- #
# The event cursor: monotonic per run and replayable
# --------------------------------------------------------------------------- #
async def test_events_use_the_spec_envelope(client, owner, agent) -> None:
    run = await _run_with_events(client, owner, agent)
    events = (await client.get(f"/api/runs/{run['id']}/events", headers=owner["headers"])).json()
    assert len(events) == 3
    for event in events:
        assert list(event) == EVENT_KEYS
        assert event["event_id"].startswith("evt_")
        assert event["event_version"] == 1
        assert event["organization_id"] == owner["organization_id"]
        assert event["run_id"] == run["id"]
        assert event["agent_id"] == agent["id"]
        assert event["source_runtime"] == "native"
        assert isinstance(event["payload"], dict)
        # An explicit UTC offset, per the contract.
        assert event["timestamp"].endswith("Z") or "+00:00" in event["timestamp"]


async def test_sequence_is_monotonic_and_the_cursor_replays_exactly(client, owner, agent) -> None:
    run = await _create_run(client, owner, agent)
    await client.post(f"/api/runs/{run['id']}/start", headers=owner["headers"])
    await client.post(
        f"/api/runs/{run['id']}/checkpoints", headers=owner["headers"], params={"step": 1}
    )
    await client.post(f"/api/runs/{run['id']}/pause", headers=owner["headers"])
    await client.post(f"/api/runs/{run['id']}/resume", headers=owner["headers"])
    await client.post(f"/api/runs/{run['id']}/complete", headers=owner["headers"])

    events = (await client.get(f"/api/runs/{run['id']}/events", headers=owner["headers"])).json()
    types = [event["event_type"] for event in events]
    assert types == [
        "run.created",
        "run.started",
        "checkpoint.created",
        "run.paused",
        "run.resumed",
        "run.completed",
    ]
    sequences = [event["sequence"] for event in events]
    assert sequences == [1, 2, 3, 4, 5, 6]

    # The cursor is exclusive: after_sequence=N returns everything after N, and
    # replaying from every prefix reproduces the tail exactly.
    for cursor in range(0, len(sequences) + 1):
        replay = (
            await client.get(
                f"/api/runs/{run['id']}/events",
                headers=owner["headers"],
                params={"after_sequence": cursor},
            )
        ).json()
        assert [event["sequence"] for event in replay] == sequences[cursor:]

    # The run row agrees with the highest persisted sequence.
    detail = (await client.get(f"/api/runs/{run['id']}", headers=owner["headers"])).json()
    assert detail["last_sequence"] == 6


async def test_org_event_feed_filters_by_run_and_type(client, owner, agent) -> None:
    first = await _run_with_events(client, owner, agent)
    second = await _create_run(client, owner, agent, directive="other")
    await client.post(f"/api/runs/{second['id']}/cancel", headers=owner["headers"])

    by_run = (
        await client.get("/api/events", headers=owner["headers"], params={"run_id": second["id"]})
    ).json()
    assert [event["run_id"] for event in by_run] == [second["id"]] * 2
    assert [event["event_type"] for event in by_run] == ["run.created", "run.cancelled"]

    by_type = (
        await client.get(
            "/api/events", headers=owner["headers"], params={"event_type": "run.completed"}
        )
    ).json()
    assert [event["event_type"] for event in by_type] == ["run.completed"]
    assert by_type[0]["run_id"] == first["id"]


async def test_concurrent_checkpoints_never_duplicate_a_sequence(client, owner, agent) -> None:
    """Regression: the read-then-write cursor could hand out one number twice."""
    run = await _create_run(client, owner, agent)
    responses = await asyncio.gather(
        *[
            client.post(
                f"/api/runs/{run['id']}/checkpoints",
                headers=owner["headers"],
                params={"step": step},
            )
            for step in range(1, 7)
        ]
    )
    assert all(response.status_code == 201 for response in responses), [
        response.text for response in responses if response.status_code != 201
    ]

    events = (await client.get(f"/api/runs/{run['id']}/events", headers=owner["headers"])).json()
    sequences = [event["sequence"] for event in events]
    assert len(sequences) == len(set(sequences)) == 7
    assert sequences == sorted(sequences)


async def test_duplicate_checkpoint_step_is_a_documented_conflict(client, owner, agent) -> None:
    """A repeated step is 409, never a raw IntegrityError (500)."""
    run = await _create_run(client, owner, agent)
    first = await client.post(
        f"/api/runs/{run['id']}/checkpoints",
        headers=owner["headers"],
        params={"step": 2, "label": "after plan"},
    )
    assert first.status_code == 201, first.text
    assert first.json()["step"] == 2
    assert first.json()["label"] == "after plan"
    assert first.json()["resumable"] is True

    second = await client.post(
        f"/api/runs/{run['id']}/checkpoints", headers=owner["headers"], params={"step": 2}
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "checkpoint_exists"


# --------------------------------------------------------------------------- #
# Transitions
# --------------------------------------------------------------------------- #
async def test_the_documented_transition_table_is_enforced(client, owner, agent) -> None:
    run = await _create_run(client, owner, agent)
    # created -> completed is illegal; created -> running is legal.
    illegal = await client.post(f"/api/runs/{run['id']}/complete", headers=owner["headers"])
    assert illegal.status_code == 409
    assert illegal.json()["error"]["code"] == "illegal_transition"

    assert (
        await client.post(f"/api/runs/{run['id']}/start", headers=owner["headers"])
    ).status_code == 200
    assert (await client.post(f"/api/runs/{run['id']}/pause", headers=owner["headers"])).json()[
        "status"
    ] == "paused"
    assert (await client.post(f"/api/runs/{run['id']}/resume", headers=owner["headers"])).json()[
        "status"
    ] == "running"
    assert (await client.post(f"/api/runs/{run['id']}/complete", headers=owner["headers"])).json()[
        "status"
    ] == "completed"

    # completed is terminal: every other target state is refused. Repeating
    # ``complete`` is an idempotent no-op (200, no state change, no extra event).
    for action in ("start", "pause", "resume"):
        response = await client.post(f"/api/runs/{run['id']}/{action}", headers=owner["headers"])
        assert response.status_code == 409, action
        assert response.json()["error"]["code"] == "illegal_transition"

    repeat = await client.post(f"/api/runs/{run['id']}/complete", headers=owner["headers"])
    assert repeat.status_code == 200
    assert repeat.json()["status"] == "completed"
    events = (await client.get(f"/api/runs/{run['id']}/events", headers=owner["headers"])).json()
    assert [event["event_type"] for event in events].count("run.completed") == 1


async def test_concurrent_transitions_have_exactly_one_winner(client, owner, agent) -> None:
    """Regression: two concurrent transitions could both emit an event."""
    run = await _create_run(client, owner, agent)
    await client.post(f"/api/runs/{run['id']}/start", headers=owner["headers"])

    responses = await asyncio.gather(
        client.post(f"/api/runs/{run['id']}/complete", headers=owner["headers"]),
        client.post(f"/api/runs/{run['id']}/cancel", headers=owner["headers"]),
    )
    codes = sorted(response.status_code for response in responses)
    assert codes == [200, 409], [response.text for response in responses]

    events = (await client.get(f"/api/runs/{run['id']}/events", headers=owner["headers"])).json()
    terminal = [
        event["event_type"]
        for event in events
        if event["event_type"] in {"run.completed", "run.cancelled"}
    ]
    assert len(terminal) == 1, f"two terminal events for one run: {terminal}"


async def test_run_detail_reports_checkpoint_and_pending_approvals(client, owner, agent) -> None:
    run = await _create_run(client, owner, agent)
    await client.post(f"/api/runs/{run['id']}/start", headers=owner["headers"])
    await client.post(
        f"/api/runs/{run['id']}/checkpoints",
        headers=owner["headers"],
        params={"step": 4, "label": "mid"},
        json={"state": {"plan": "ok"}},
    )
    detail = (await client.get(f"/api/runs/{run['id']}", headers=owner["headers"])).json()
    assert detail["latest_checkpoint_step"] == 4
    assert detail["pending_approvals"] == 0
    assert detail["status"] == "running"


async def test_runs_can_be_filtered_by_status_and_agent(client, owner, agent) -> None:
    first = await _create_run(client, owner, agent)
    second = await _create_run(client, owner, agent, directive="second")
    await client.post(f"/api/runs/{second['id']}/cancel", headers=owner["headers"])

    running = await client.get("/api/runs", headers=owner["headers"], params={"status": "created"})
    assert [row["id"] for row in running.json()["items"]] == [first["id"]]

    cancelled = await client.get(
        "/api/runs", headers=owner["headers"], params={"status": "cancelled"}
    )
    assert [row["id"] for row in cancelled.json()["items"]] == [second["id"]]

    by_agent = await client.get(
        "/api/runs", headers=owner["headers"], params={"agent_id": agent["id"]}
    )
    assert by_agent.json()["total"] == 2


# --------------------------------------------------------------------------- #
# Approvals are decided exactly once
# --------------------------------------------------------------------------- #
async def _pending_approval(client, owner) -> str:
    await client.post("/api/tools/sync-builtin", headers=owner["headers"])
    await client.put("/api/system/autonomy", headers=owner["headers"], json={"level": "0"})
    invoked = await client.post(
        "/api/tools/invoke",
        headers=owner["headers"],
        json={"tool_slug": "calc.evaluate", "arguments": {"expression": "3*3"}},
    )
    assert invoked.status_code == 200, invoked.text
    assert invoked.json()["outcome"] == "awaiting_approval"
    approval_id = invoked.json()["approval_id"]
    assert isinstance(approval_id, str) and approval_id
    return approval_id


async def test_approval_decision_is_final(client, owner, agent) -> None:
    approval_id = await _pending_approval(client, owner)
    first = await client.post(
        f"/api/approvals/{approval_id}/decide",
        headers=owner["headers"],
        json={"approve": True, "note": "ok"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "approved"
    assert first.json()["decided_by"] == owner["user_id"]
    assert first.json()["decided_at"] is not None

    second = await client.post(
        f"/api/approvals/{approval_id}/decide",
        headers=owner["headers"],
        json={"approve": False},
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "approval_not_pending"


async def test_concurrent_approval_decisions_have_one_winner(client, owner, agent) -> None:
    """Regression: approve and reject could both succeed and both be emitted."""
    approval_id = await _pending_approval(client, owner)
    responses = await asyncio.gather(
        client.post(
            f"/api/approvals/{approval_id}/decide", headers=owner["headers"], json={"approve": True}
        ),
        client.post(
            f"/api/approvals/{approval_id}/decide",
            headers=owner["headers"],
            json={"approve": False},
        ),
    )
    assert sorted(response.status_code for response in responses) == [200, 409], [
        response.text for response in responses
    ]

    decided = [response for response in responses if response.status_code == 200]
    assert len(decided) == 1
    final_status = decided[0].json()["status"]

    feed = (await client.get("/api/events", headers=owner["headers"])).json()
    decision_events = [
        event["event_type"]
        for event in feed
        if event["event_type"].startswith("approval.")
        and event["event_type"] != "approval.requested"
    ]
    assert len(decision_events) == 1, f"two decisions recorded: {decision_events}"
    assert decision_events[0] == f"approval.{final_status}"


async def test_viewer_cannot_decide_an_approval(client, viewer, owner) -> None:
    approval_id = await _pending_approval(client, owner)
    response = await client.post(
        f"/api/approvals/{approval_id}/decide", headers=viewer["headers"], json={"approve": True}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_unknown_approval_is_404(client, owner) -> None:
    response = await client.post(
        "/api/approvals/apr_does_not_exist/decide", headers=owner["headers"], json={"approve": True}
    )
    assert response.status_code == 404
