"""Event log contract: sequences, cursors, redaction and the error envelope.

These tests target ``app/api/routes/agents.py`` + ``runs.py`` event endpoints and
the ``app/services/event_service.py`` guarantees they stand on, so the SPEC §7
rules ("sequence is monotonic per run", "payloads are secret-redacted",
"after_sequence replays the tail") are enforced by evidence rather than by
reading the code.
"""

from __future__ import annotations

import asyncio

import pytest
from app.core.errors import ValidationFailedError
from app.services import event_service
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.asyncio


async def _run(client, owner, agent) -> dict:
    response = await client.post(
        "/api/runs",
        headers=owner["headers"],
        json={"agent_id": agent["id"], "directive": "emit events"},
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# Sequence allocation
# --------------------------------------------------------------------------- #
async def test_reserve_sequence_is_gapless_and_atomic(client, owner, agent, session_factory):
    run = await _run(client, owner, agent)
    async with session_factory() as session:
        # ``run.created`` already reserved 1.
        reserved = [await event_service.reserve_sequence(session, run["id"]) for _ in range(3)]
        await session.commit()
    assert reserved == [2, 3, 4]

    detail = (await client.get(f"/api/runs/{run['id']}", headers=owner["headers"])).json()
    assert detail["last_sequence"] == 4


async def test_concurrent_reservations_are_unique(client, owner, agent, session_factory):
    run = await _run(client, owner, agent)

    async def reserve() -> int:
        async with session_factory() as session:
            value = await event_service.reserve_sequence(session, run["id"])
            await session.commit()
            return value

    values = await asyncio.gather(*[reserve() for _ in range(6)])
    assert len(set(values)) == len(values) == 6
    assert sorted(values) == [2, 3, 4, 5, 6, 7]


async def test_explicit_sequence_is_honoured_and_duplicates_are_refused(
    client, owner, agent, session_factory
):
    run = await _run(client, owner, agent)
    async with session_factory() as session:
        first = await event_service.append_event(
            session,
            organization_id=owner["organization_id"],
            run_id=run["id"],
            event_type="agent.message",
            sequence=50,
        )
        await session.commit()
        assert first.sequence == 50

        with pytest.raises(IntegrityError):
            await event_service.append_event(
                session,
                organization_id=owner["organization_id"],
                run_id=run["id"],
                event_type="agent.message",
                sequence=50,
            )
            await session.flush()

    # An explicit sequence is the caller's assertion that it is beyond the current
    # high-water mark; writing it does not move the run's counter, so the ordinary
    # reservation path stays gap-free (2) instead of jumping to 51. A caller that
    # wants to advance the cursor must reserve, not invent.
    async with session_factory() as session:
        assert await event_service.reserve_sequence(session, run["id"]) == 2


async def test_unknown_run_cannot_allocate_a_sequence(owner, session_factory):
    async with session_factory() as session:
        with pytest.raises(ValidationFailedError):
            await event_service.reserve_sequence(session, "run_does_not_exist")


async def test_unknown_event_type_is_refused_before_anything_is_written(
    client, owner, agent, session_factory
):
    run = await _run(client, owner, agent)
    async with session_factory() as session:
        with pytest.raises(ValidationFailedError) as error:
            await event_service.append_event(
                session,
                organization_id=owner["organization_id"],
                run_id=run["id"],
                event_type="definitely.not.an.event",
            )
        assert error.value.code == "unknown_event_type"
        assert "run.created" in error.value.details["allowed"]

    events = (await client.get(f"/api/runs/{run['id']}/events", headers=owner["headers"])).json()
    assert [event["event_type"] for event in events] == ["run.created"]


# --------------------------------------------------------------------------- #
# Payload redaction (SPEC §7: payloads are secret-redacted)
# --------------------------------------------------------------------------- #
async def test_secrets_in_a_payload_are_redacted(client, owner, agent, session_factory):
    run = await _run(client, owner, agent)
    async with session_factory() as session:
        event = await event_service.append_event(
            session,
            organization_id=owner["organization_id"],
            run_id=run["id"],
            event_type="agent.message",
            payload={
                "api_key": "sk-live-should-never-be-stored",
                "nested": {"password": "hunter2", "safe": "visible"},
                "note": "keep me",
            },
        )
        await session.commit()
        payload = event.payload

    assert payload["note"] == "keep me"
    assert payload["api_key"] != "sk-live-should-never-be-stored"
    assert payload["nested"]["password"] != "hunter2"
    assert payload["nested"]["safe"] == "visible"

    wire = (await client.get(f"/api/runs/{run['id']}/events", headers=owner["headers"])).json()
    stored = [event for event in wire if event["event_type"] == "agent.message"][0]
    assert "sk-live-should-never-be-stored" not in str(stored)
    assert "hunter2" not in str(stored)


# --------------------------------------------------------------------------- #
# Cursor semantics
# --------------------------------------------------------------------------- #
async def test_cursor_is_exclusive_and_never_repeats(client, owner, agent) -> None:
    run = await _run(client, owner, agent)
    for step in (1, 2, 3):
        await client.post(
            f"/api/runs/{run['id']}/checkpoints", headers=owner["headers"], params={"step": step}
        )

    everything = (
        await client.get(f"/api/runs/{run['id']}/events", headers=owner["headers"])
    ).json()
    assert [event["sequence"] for event in everything] == [1, 2, 3, 4]

    seen: list[str] = []
    cursor = 0
    while True:
        batch = (
            await client.get(
                f"/api/runs/{run['id']}/events",
                headers=owner["headers"],
                params={"after_sequence": cursor, "limit": 2},
            )
        ).json()
        if not batch:
            break
        assert all(event["sequence"] > cursor for event in batch)
        seen.extend(event["event_id"] for event in batch)
        cursor = batch[-1]["sequence"]

    # Paging with a cursor visits every event exactly once.
    assert seen == [event["event_id"] for event in everything]


async def test_limit_bounds_the_batch(client, owner, agent) -> None:
    run = await _run(client, owner, agent)
    for step in (1, 2, 3, 4):
        await client.post(
            f"/api/runs/{run['id']}/checkpoints", headers=owner["headers"], params={"step": step}
        )
    batch = (
        await client.get(
            f"/api/runs/{run['id']}/events", headers=owner["headers"], params={"limit": 2}
        )
    ).json()
    assert len(batch) == 2
    assert [event["sequence"] for event in batch] == [1, 2]


async def test_sequences_are_independent_per_run(client, owner, agent) -> None:
    first = await _run(client, owner, agent)
    second = await _run(client, owner, agent)
    await client.post(f"/api/runs/{second['id']}/start", headers=owner["headers"])

    first_events = (
        await client.get(f"/api/runs/{first['id']}/events", headers=owner["headers"])
    ).json()
    second_events = (
        await client.get(f"/api/runs/{second['id']}/events", headers=owner["headers"])
    ).json()
    assert [event["sequence"] for event in first_events] == [1]
    assert [event["sequence"] for event in second_events] == [1, 2]


# --------------------------------------------------------------------------- #
# Error envelope
# --------------------------------------------------------------------------- #
async def test_bad_query_parameters_use_the_error_envelope(client, owner, agent) -> None:
    run = await _run(client, owner, agent)
    for params in ({"after_sequence": -1}, {"limit": 0}, {"limit": 5000}):
        response = await client.get(
            f"/api/runs/{run['id']}/events", headers=owner["headers"], params=params
        )
        assert response.status_code == 422, params
        assert response.json()["error"]["code"] == "validation_failed"


async def test_a_foreign_run_id_is_404_not_an_empty_feed(client, owner, agent, second_tenant):
    run = await _run(client, owner, agent)
    response = await client.get(
        "/api/events", headers=second_tenant["headers"], params={"run_id": run["id"]}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_any_integrity_error_becomes_a_documented_conflict(owner) -> None:
    """The last-resort handler must never leak a 500 with a driver message."""
    from app.core.config import Settings
    from app.main import create_app

    app = create_app(Settings(jwt_secret="x" * 40, database_url="sqlite+aiosqlite:///:memory:"))

    @app.get("/api/_tests/integrity")
    async def _boom() -> None:
        raise IntegrityError("INSERT ...", {}, Exception("UNIQUE constraint failed: secret_value"))

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/_tests/integrity")
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "conflict"
    assert "secret_value" not in str(body)
