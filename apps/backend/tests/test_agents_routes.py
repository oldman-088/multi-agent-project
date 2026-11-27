"""REST contract tests for the agent and conversation routes (docs/API.md §4).

Scope: authentication (AGENTS.md Q5), tenant isolation at the service layer, the
immutable-version rules, and the chat message ordering guarantees of
``app/api/routes/agents.py``.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.asyncio

# Every route exposed by app/api/routes/agents.py, with a body where one is needed.
AGENT_ROUTES: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/agents", None),
    ("POST", "/api/agents", {"name": "X", "role": "backend"}),
    ("GET", "/api/agents/agt_x", None),
    ("PATCH", "/api/agents/agt_x", {"name": "Y"}),
    ("POST", "/api/agents/agt_x/clone", None),
    ("POST", "/api/agents/agt_x/enable?enabled=true", None),
    ("DELETE", "/api/agents/agt_x", None),
    ("GET", "/api/agents/agt_x/versions", None),
    ("GET", "/api/agents/agt_x/versions/1", None),
    ("GET", "/api/agents/agt_x/versions/1/diff/2", None),
    ("GET", "/api/agents/agt_x/tools", None),
    ("POST", "/api/conversations", {"agent_id": "agt_x", "title": "t"}),
    ("GET", "/api/conversations", None),
    ("GET", "/api/conversations/cnv_x/messages", None),
    ("POST", "/api/conversations/cnv_x/messages", {"content": "hi"}),
]


# --------------------------------------------------------------------------- #
# Authentication and authorization
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path", "body"), AGENT_ROUTES)
async def test_agent_routes_require_credentials(
    client, owner, method: str, path: str, body: dict | None
) -> None:
    """Q5: no credentials must yield 401 with the documented error code."""
    response = await client.request(method, path, json=body)
    assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
    assert response.json()["error"]["code"] in {
        "unauthenticated",
        "invalid_token",
        "token_expired",
        "wrong_token_type",
    }


@pytest.mark.parametrize(("method", "path", "body"), AGENT_ROUTES)
async def test_agent_routes_require_credentials_on_the_right_router(
    client, owner, method: str, path: str, body: dict | None
) -> None:
    """A bad token is rejected the same way, so the router itself is protected."""
    response = await client.request(
        method, path, json=body, headers={"Authorization": "Bearer nope"}
    )
    assert response.status_code == 401


async def test_viewer_may_read_agents_but_not_write(client, viewer, agent) -> None:
    read = await client.get(f"/api/agents/{agent['id']}", headers=viewer["headers"])
    assert read.status_code == 200
    assert read.json()["id"] == agent["id"]

    for method, path, body in (
        ("POST", "/api/agents", {"name": "Nope", "role": "backend"}),
        ("PATCH", f"/api/agents/{agent['id']}", {"name": "Nope"}),
        ("POST", f"/api/agents/{agent['id']}/clone", None),
        ("DELETE", f"/api/agents/{agent['id']}", None),
        ("POST", "/api/conversations", {"agent_id": agent["id"], "title": "t"}),
    ):
        response = await client.request(method, path, headers=viewer["headers"], json=body)
        assert response.status_code == 403, f"{method} {path} -> {response.status_code}"
        assert response.json()["error"]["code"] == "forbidden"


# --------------------------------------------------------------------------- #
# Tenant isolation (RBAC enforced in the service layer)
# --------------------------------------------------------------------------- #
async def test_other_organization_cannot_read_an_agent_or_its_versions(
    client, agent, second_tenant
) -> None:
    headers = second_tenant["headers"]
    for path in (
        f"/api/agents/{agent['id']}",
        f"/api/agents/{agent['id']}/versions",
        f"/api/agents/{agent['id']}/versions/1",
        f"/api/agents/{agent['id']}/versions/1/diff/2",
        f"/api/agents/{agent['id']}/tools",
    ):
        response = await client.get(path, headers=headers)
        assert response.status_code == 404, f"{path} leaked -> {response.status_code}"
        assert response.json()["error"]["code"] == "not_found"


async def test_other_organization_cannot_modify_an_agent(
    client, owner, agent, second_tenant
) -> None:
    headers = second_tenant["headers"]
    for method, path, body in (
        ("PATCH", f"/api/agents/{agent['id']}", {"name": "Hijacked"}),
        ("POST", f"/api/agents/{agent['id']}/clone", None),
        ("POST", f"/api/agents/{agent['id']}/enable?enabled=false", None),
        ("DELETE", f"/api/agents/{agent['id']}", None),
    ):
        response = await client.request(method, path, headers=headers, json=body)
        assert response.status_code == 404, f"{method} {path} -> {response.status_code}"

    # The agent is untouched for its real owner.
    owner_view = await client.get(f"/api/agents/{agent['id']}", headers=owner["headers"])
    assert owner_view.status_code == 200
    assert owner_view.json()["name"] == agent["name"]
    assert owner_view.json()["is_enabled"] is True
    assert owner_view.json()["is_archived"] is False


async def test_other_organization_cannot_touch_a_conversation(client, owner, agent, second_tenant):
    created = await client.post(
        "/api/conversations",
        headers=owner["headers"],
        json={"agent_id": agent["id"], "title": "private"},
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]

    headers = second_tenant["headers"]
    read = await client.get(f"/api/conversations/{conversation_id}/messages", headers=headers)
    assert read.status_code == 404
    write = await client.post(
        f"/api/conversations/{conversation_id}/messages", headers=headers, json={"content": "x"}
    )
    assert write.status_code == 404

    # Conversations of another organization also stay out of the list.
    listed = await client.get("/api/conversations", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 0


async def test_agent_list_is_scoped_to_the_caller_organization(client, owner, agent, second_tenant):
    owner_list = await client.get("/api/agents", headers=owner["headers"])
    assert owner_list.json()["total"] == 1
    other_list = await client.get("/api/agents", headers=second_tenant["headers"])
    assert other_list.json()["total"] == 0


async def test_conversation_cannot_be_started_for_a_foreign_agent(
    client, owner, agent, second_tenant
):
    response = await client.post(
        "/api/conversations",
        headers=second_tenant["headers"],
        json={"agent_id": agent["id"], "title": "steal"},
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Immutable versions
# --------------------------------------------------------------------------- #
async def test_every_save_appends_a_version_and_never_mutates_one(client, owner, agent) -> None:
    first = await client.get(f"/api/agents/{agent['id']}/versions/1", headers=owner["headers"])
    assert first.status_code == 200
    before = first.json()

    patched = await client.patch(
        f"/api/agents/{agent['id']}",
        headers=owner["headers"],
        json={"instructions": "Always write tests", "change_note": "tighten instructions"},
    )
    assert patched.status_code == 200
    assert patched.json()["current_version"] == 2

    # Version 1 is byte-for-byte what it was: versions are immutable snapshots.
    again = await client.get(f"/api/agents/{agent['id']}/versions/1", headers=owner["headers"])
    assert again.json() == before

    second = await client.get(f"/api/agents/{agent['id']}/versions/2", headers=owner["headers"])
    assert second.json()["instructions"] == "Always write tests"
    assert second.json()["change_note"] == "tighten instructions"

    history = await client.get(f"/api/agents/{agent['id']}/versions", headers=owner["headers"])
    assert [row["version"] for row in history.json()] == [2, 1]

    diff = await client.get(
        f"/api/agents/{agent['id']}/versions/1/diff/2", headers=owner["headers"]
    )
    assert diff.status_code == 200
    assert diff.json()["changed_fields"]["instructions"] == {
        "from": "Follow docs/SPEC.md",
        "to": "Always write tests",
    }


async def test_unknown_version_is_404(client, owner, agent) -> None:
    response = await client.get(f"/api/agents/{agent['id']}/versions/99", headers=owner["headers"])
    assert response.status_code == 404


async def test_agent_tools_endpoint_returns_the_allow_list(client, owner, agent) -> None:
    response = await client.get(f"/api/agents/{agent['id']}/tools", headers=owner["headers"])
    assert response.status_code == 200
    assert response.json() == ["calc.evaluate", "time.now"]


async def test_archived_agents_are_hidden_unless_requested(client, owner, agent) -> None:
    assert (
        await client.delete(f"/api/agents/{agent['id']}", headers=owner["headers"])
    ).status_code == 200
    assert (await client.get("/api/agents", headers=owner["headers"])).json()["total"] == 0
    archived = await client.get(
        "/api/agents", headers=owner["headers"], params={"include_archived": True}
    )
    assert archived.json()["total"] == 1


# --------------------------------------------------------------------------- #
# Chat ordering
# --------------------------------------------------------------------------- #
async def test_messages_are_returned_in_a_total_order(client, owner, agent) -> None:
    conversation = (
        await client.post(
            "/api/conversations",
            headers=owner["headers"],
            json={"agent_id": agent["id"], "title": "order"},
        )
    ).json()
    for index in range(3):
        sent = await client.post(
            f"/api/conversations/{conversation['id']}/messages",
            headers=owner["headers"],
            json={"content": f"message {index}"},
        )
        assert sent.status_code == 201, sent.text
        # ``usage`` is honestly null: no connection reported it.
        assert sent.json()["usage"] is None
        assert sent.json()["role"] == "user"

    messages = (
        await client.get(
            f"/api/conversations/{conversation['id']}/messages", headers=owner["headers"]
        )
    ).json()
    assert [row["sequence"] for row in messages] == [1, 2, 3]
    assert [row["content"] for row in messages] == ["message 0", "message 1", "message 2"]


async def test_concurrent_messages_never_share_a_sequence(client, owner, agent) -> None:
    """Regression: ``MAX(sequence)+1`` gave concurrent sends the same number."""
    conversation = (
        await client.post(
            "/api/conversations",
            headers=owner["headers"],
            json={"agent_id": agent["id"], "title": "race"},
        )
    ).json()

    responses = await asyncio.gather(
        *[
            client.post(
                f"/api/conversations/{conversation['id']}/messages",
                headers=owner["headers"],
                json={"content": f"m{index}"},
            )
            for index in range(6)
        ]
    )
    assert all(response.status_code == 201 for response in responses), [
        response.text for response in responses if response.status_code != 201
    ]

    messages = (
        await client.get(
            f"/api/conversations/{conversation['id']}/messages", headers=owner["headers"]
        )
    ).json()
    sequences = [row["sequence"] for row in messages]
    assert len(sequences) == 6
    assert len(set(sequences)) == 6, f"duplicate message sequences: {sequences}"
    assert sequences == sorted(sequences)
    assert sequences == list(range(1, 7))


async def test_message_body_is_validated(client, owner, agent) -> None:
    conversation = (
        await client.post(
            "/api/conversations",
            headers=owner["headers"],
            json={"agent_id": agent["id"], "title": "validation"},
        )
    ).json()
    empty = await client.post(
        f"/api/conversations/{conversation['id']}/messages",
        headers=owner["headers"],
        json={"content": ""},
    )
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "validation_failed"
