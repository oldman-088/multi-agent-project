"""End-to-end tests against a live bridge process (real WebSocket + HTTP on loopback).

The tests play both roles: the userscript (WebSocket client) and the backend (HTTP client).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app import BridgeSettings, create_app
from conftest import LiveBridge

VERSION = "1.0.0"


def run(coro: Any) -> Any:
    return asyncio.run(coro)


async def recv_json(ws: ClientConnection, timeout: float = 3.0) -> dict[str, Any]:
    data = json.loads(await asyncio.wait_for(ws.recv(), timeout))
    assert isinstance(data, dict)
    return data


async def expect_close(ws: ClientConnection) -> int:
    with pytest.raises(ConnectionClosed) as info:
        await asyncio.wait_for(ws.recv(), 3.0)
    code = info.value.rcvd.code if info.value.rcvd is not None else -1
    return int(code)


async def pair_device(live: LiveBridge) -> tuple[str, str]:
    async with httpx.AsyncClient(base_url=live.base) as http:
        resp = await http.post("/api/pairing-codes", headers=_auth(live))
        assert resp.status_code == 200
        code = resp.json()["code"]
    async with connect(live.ws_url, origin=live.origin) as ws:
        await ws.send(
            json.dumps(
                {"type": "hello", "script_version": VERSION, "pairing_code": code}
            )
        )
        msg = await recv_json(ws)
        assert msg["type"] == "paired"
        return str(msg["device_id"]), str(msg["credential"])


async def open_device(
    live: LiveBridge, device_id: str, credential: str
) -> ClientConnection:
    ws = await connect(live.ws_url, origin=live.origin)
    await ws.send(
        json.dumps(
            {
                "type": "hello",
                "script_version": VERSION,
                "device_id": device_id,
                "credential": credential,
            }
        )
    )
    welcome = await recv_json(ws)
    assert welcome["type"] == "welcome"
    assert welcome["session_state"] == "AUTHENTICATED"
    return ws


async def send_state(ws: ClientConnection, tab: str, state: str) -> None:
    await ws.send(json.dumps({"type": "tab_state", "tab_id": tab, "state": state}))


def _auth(live: LiveBridge) -> dict[str, str]:
    return {"Authorization": f"Bearer {live.token}"}


async def find_tab_id(http: httpx.AsyncClient, live: LiveBridge) -> str:
    resp = await http.get("/api/tabs", headers=_auth(live))
    tabs = resp.json()
    assert tabs, "no tab registered"
    return str(tabs[0]["tab_id"])


async def post_request(
    http: httpx.AsyncClient,
    live: LiveBridge,
    tab_id: str,
    prompt: str,
    key: str,
    timeout_s: float = 30,
) -> dict[str, Any]:
    resp = await http.post(
        f"/api/tabs/{tab_id}/requests",
        headers=_auth(live),
        json={"prompt": prompt, "idempotency_key": key, "timeout_s": timeout_s},
    )
    assert resp.status_code == 202, resp.text
    return dict(resp.json())


async def poll_until_done(
    http: httpx.AsyncClient,
    live: LiveBridge,
    tab_id: str,
    request_id: str,
    timeout: float = 5.0,
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        resp = await http.get(
            f"/api/tabs/{tab_id}/requests/{request_id}", headers=_auth(live)
        )
        body = dict(resp.json())
        if body["status"] in {"completed", "failed", "cancelled"}:
            return body
        if loop.time() > deadline:
            raise AssertionError(f"request still {body['status']}")
        await asyncio.sleep(0.05)


# ----- public surface and authentication ------------------------------------


def test_health_is_public_and_reveals_no_secrets(live_bridge: LiveBridge) -> None:
    async def scenario() -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=live_bridge.base) as http:
            resp = await http.get("/health")
            assert resp.status_code == 200
            return dict(resp.json())

    body = run(scenario())
    assert body["status"] == "ok"
    assert live_bridge.token not in json.dumps(body)


def test_every_api_route_refuses_missing_credentials(live_bridge: LiveBridge) -> None:
    routes = [
        ("POST", "/api/pairing-codes"),
        ("GET", "/api/devices"),
        ("POST", "/api/devices/dev_x/revoke"),
        ("GET", "/api/tabs"),
        ("POST", "/api/tabs/tab_x/requests"),
        ("GET", "/api/tabs/tab_x/requests/req_x"),
        ("POST", "/api/tabs/tab_x/requests/req_x/cancel"),
    ]

    async def scenario() -> list[tuple[str, str, int]]:
        results = []
        async with httpx.AsyncClient(base_url=live_bridge.base) as http:
            for method, path in routes:
                no_auth = await http.request(
                    method, path, json={"prompt": "x", "idempotency_key": "k"}
                )
                wrong = await http.request(
                    method,
                    path,
                    headers={
                        "Authorization": "Bearer not-the-token-at-all-but-long-enough-1234"
                    },
                    json={"prompt": "x", "idempotency_key": "k"},
                )
                results.append((method, path, no_auth.status_code))
                results.append((method, path, wrong.status_code))
        return results

    for method, path, status in run(scenario()):
        assert status in {401, 403}, (
            f"{method} {path} answered {status} without valid credentials"
        )


def test_api_is_unavailable_when_no_token_is_configured() -> None:
    settings = BridgeSettings(api_token_digest=None, allowed_origins=frozenset())
    app = create_app(settings)

    async def scenario() -> int:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1"
        ) as http:
            resp = await http.get(
                "/api/tabs", headers={"Authorization": "Bearer " + "y" * 40}
            )
            return resp.status_code

    assert run(scenario()) == 503


def test_settings_reject_short_token_and_bad_origin() -> None:
    with pytest.raises(ValueError):
        BridgeSettings.from_env({"BRIDGE_API_TOKEN": "short"})
    with pytest.raises(ValueError):
        BridgeSettings.from_env({"BRIDGE_ALLOWED_ORIGINS": "https://example.com/path"})
    with pytest.raises(ValueError):
        BridgeSettings.from_env({"BRIDGE_PORT": "80"})


def test_default_settings_allow_no_origin() -> None:
    settings = BridgeSettings.from_env({})
    assert settings.allowed_origins == frozenset()
    assert settings.api_token_digest is None


# ----- WebSocket handshake: origin, version, pairing, credentials -----------


def test_origin_refused_for_foreign_origin(live_bridge: LiveBridge) -> None:
    async def scenario() -> int:
        async with connect(live_bridge.ws_url, origin="https://evil.example") as ws:
            return await expect_close(ws)

    assert run(scenario()) == 4403


def test_origin_refused_when_header_missing(live_bridge: LiveBridge) -> None:
    async def scenario() -> int:
        async with connect(live_bridge.ws_url) as ws:
            return await expect_close(ws)

    assert run(scenario()) == 4403


def test_origin_check_is_exact_not_prefix(live_bridge: LiveBridge) -> None:
    async def scenario() -> int:
        async with connect(
            live_bridge.ws_url, origin=live_bridge.origin + ".evil.example"
        ) as ws:
            return await expect_close(ws)

    assert run(scenario()) == 4403


def test_old_script_is_refused(live_bridge: LiveBridge) -> None:
    async def scenario() -> int:
        async with connect(live_bridge.ws_url, origin=live_bridge.origin) as ws:
            await ws.send(
                json.dumps(
                    {"type": "hello", "script_version": "0.9.9", "pairing_code": "X"}
                )
            )
            return await expect_close(ws)

    assert run(scenario()) == 4409


def test_bad_pairing_code_is_refused(live_bridge: LiveBridge) -> None:
    async def scenario() -> int:
        async with connect(live_bridge.ws_url, origin=live_bridge.origin) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "hello",
                        "script_version": VERSION,
                        "pairing_code": "NOPE1234",
                    }
                )
            )
            return await expect_close(ws)

    assert run(scenario()) == 4402


def test_pairing_code_cannot_be_reused(live_bridge: LiveBridge) -> None:
    async def scenario() -> int:
        async with httpx.AsyncClient(base_url=live_bridge.base) as http:
            code = (
                await http.post("/api/pairing-codes", headers=_auth(live_bridge))
            ).json()["code"]
        async with connect(live_bridge.ws_url, origin=live_bridge.origin) as ws:
            await ws.send(
                json.dumps(
                    {"type": "hello", "script_version": VERSION, "pairing_code": code}
                )
            )
            assert (await recv_json(ws))["type"] == "paired"
        async with connect(live_bridge.ws_url, origin=live_bridge.origin) as ws:
            await ws.send(
                json.dumps(
                    {"type": "hello", "script_version": VERSION, "pairing_code": code}
                )
            )
            return await expect_close(ws)

    assert run(scenario()) == 4402


def test_hello_without_credentials_requires_pairing(live_bridge: LiveBridge) -> None:
    async def scenario() -> tuple[str, int]:
        async with connect(live_bridge.ws_url, origin=live_bridge.origin) as ws:
            await ws.send(json.dumps({"type": "hello", "script_version": VERSION}))
            first = await recv_json(ws)
            return str(first["type"]), await expect_close(ws)

    kind, code = run(scenario())
    assert kind == "pairing_required"
    assert code == 4404


def test_paired_device_reconnects_with_credential(live_bridge: LiveBridge) -> None:
    async def scenario() -> None:
        device_id, credential = await pair_device(live_bridge)
        ws = await open_device(live_bridge, device_id, credential)
        await ws.close()

    run(scenario())


def test_wrong_credential_is_refused(live_bridge: LiveBridge) -> None:
    async def scenario() -> int:
        device_id, _ = await pair_device(live_bridge)
        async with connect(live_bridge.ws_url, origin=live_bridge.origin) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "hello",
                        "script_version": VERSION,
                        "device_id": device_id,
                        "credential": "bogus",
                    }
                )
            )
            return await expect_close(ws)

    assert run(scenario()) == 4401


def test_unknown_device_is_refused(live_bridge: LiveBridge) -> None:
    async def scenario() -> int:
        async with connect(live_bridge.ws_url, origin=live_bridge.origin) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "hello",
                        "script_version": VERSION,
                        "device_id": "dev_nope",
                        "credential": "x",
                    }
                )
            )
            return await expect_close(ws)

    assert run(scenario()) == 4404


def test_revocation_closes_live_socket_and_refuses_reconnect(
    live_bridge: LiveBridge,
) -> None:
    async def scenario() -> tuple[int, int]:
        device_id, credential = await pair_device(live_bridge)
        ws = await open_device(live_bridge, device_id, credential)
        async with httpx.AsyncClient(base_url=live_bridge.base) as http:
            resp = await http.post(
                f"/api/devices/{device_id}/revoke", headers=_auth(live_bridge)
            )
            assert resp.status_code == 200
        live_code = await expect_close(ws)
        async with connect(live_bridge.ws_url, origin=live_bridge.origin) as ws2:
            await ws2.send(
                json.dumps(
                    {
                        "type": "hello",
                        "script_version": VERSION,
                        "device_id": device_id,
                        "credential": credential,
                    }
                )
            )
            return live_code, await expect_close(ws2)

    live_code, reconnect_code = run(scenario())
    assert live_code == 4410
    assert reconnect_code == 4410


def test_malformed_frame_closes_with_bad_message(live_bridge: LiveBridge) -> None:
    async def scenario() -> int:
        device_id, credential = await pair_device(live_bridge)
        ws = await open_device(live_bridge, device_id, credential)
        await ws.send("this is not json")
        return await expect_close(ws)

    assert run(scenario()) == 4400


def test_invalid_message_after_auth_gets_error_and_keeps_socket(
    live_bridge: LiveBridge,
) -> None:
    async def scenario() -> dict[str, Any]:
        device_id, credential = await pair_device(live_bridge)
        ws = await open_device(live_bridge, device_id, credential)
        await ws.send(
            json.dumps({"type": "tab_state", "tab_id": "t1", "state": "NOT_A_STATE"})
        )
        error = await recv_json(ws)
        await ws.send(json.dumps({"type": "heartbeat"}))
        ack = await recv_json(ws)
        await ws.close()
        assert ack["type"] == "heartbeat_ack"
        return error

    error = run(scenario())
    assert error == {"type": "error", "code": "BAD_MESSAGE"}


# ----- request routing ---------------------------------------------------------


def test_request_round_trip_streams_and_returns_text(live_bridge: LiveBridge) -> None:
    async def scenario() -> dict[str, Any]:
        device_id, credential = await pair_device(live_bridge)
        ws = await open_device(live_bridge, device_id, credential)
        await send_state(ws, "t1", "READY")
        async with httpx.AsyncClient(base_url=live_bridge.base) as http:
            tab = await find_tab_id(http, live_bridge)
            queued = await post_request(http, live_bridge, tab, "say hello", "key-1")
            assert queued["status"] in {"queued", "dispatched"}
            msg = await recv_json(ws)
            assert msg["type"] == "request"
            assert msg["prompt"] == "say hello"
            assert msg["tab_id"] == "t1"
            assert msg["idempotency_key"] == "key-1"
            await ws.send(
                json.dumps(
                    {"type": "delta", "request_id": msg["request_id"], "text": "Hel"}
                )
            )
            await ws.send(
                json.dumps(
                    {"type": "delta", "request_id": msg["request_id"], "text": "lo"}
                )
            )
            await ws.send(
                json.dumps(
                    {
                        "type": "result",
                        "request_id": msg["request_id"],
                        "status": "completed",
                        "text": "Hello",
                    }
                )
            )
            final = await poll_until_done(http, live_bridge, tab, queued["request_id"])
        await ws.close()
        return final

    final = run(scenario())
    assert final["status"] == "completed"
    assert final["text"] == "Hello"
    assert final["error_code"] is None
    assert "usage" not in final  # usage is never invented for browser sessions


def test_one_in_flight_request_per_tab_and_queue_position(
    live_bridge: LiveBridge,
) -> None:
    async def scenario() -> tuple[int, dict[str, Any], dict[str, Any]]:
        device_id, credential = await pair_device(live_bridge)
        ws = await open_device(live_bridge, device_id, credential)
        await send_state(ws, "t1", "READY")
        async with httpx.AsyncClient(base_url=live_bridge.base) as http:
            tab = await find_tab_id(http, live_bridge)
            first = await post_request(http, live_bridge, tab, "first", "k1")
            second = await post_request(http, live_bridge, tab, "second", "k2")
            assert second["queue_position"] == 1
            m1 = await recv_json(ws)
            assert m1["prompt"] == "first"
            # The second request must not reach the page while the first is in flight.
            with pytest.raises(TimeoutError):
                await recv_json(ws, timeout=0.4)
            await ws.send(
                json.dumps(
                    {
                        "type": "result",
                        "request_id": m1["request_id"],
                        "status": "completed",
                        "text": "one",
                    }
                )
            )
            m2 = await recv_json(ws)
            assert m2["prompt"] == "second"
            await ws.send(
                json.dumps(
                    {
                        "type": "result",
                        "request_id": m2["request_id"],
                        "status": "completed",
                        "text": "two",
                    }
                )
            )
            done1 = await poll_until_done(http, live_bridge, tab, first["request_id"])
            done2 = await poll_until_done(http, live_bridge, tab, second["request_id"])
        await ws.close()
        return 1, done1, done2

    _, done1, done2 = run(scenario())
    assert (done1["text"], done2["text"]) == ("one", "two")


def test_waiting_for_user_blocks_dispatch_until_ready(live_bridge: LiveBridge) -> None:
    async def scenario() -> dict[str, Any]:
        device_id, credential = await pair_device(live_bridge)
        ws = await open_device(live_bridge, device_id, credential)
        await send_state(ws, "t1", "WAITING_FOR_USER")
        async with httpx.AsyncClient(base_url=live_bridge.base) as http:
            tab = await find_tab_id(http, live_bridge)
            req = await post_request(http, live_bridge, tab, "blocked", "k-wait")
            with pytest.raises(TimeoutError):
                await recv_json(ws, timeout=0.4)
            await send_state(ws, "t1", "READY")
            msg = await recv_json(ws)
            assert msg["prompt"] == "blocked"
            await ws.send(
                json.dumps(
                    {
                        "type": "result",
                        "request_id": msg["request_id"],
                        "status": "completed",
                        "text": "ok",
                    }
                )
            )
            final = await poll_until_done(http, live_bridge, tab, req["request_id"])
        await ws.close()
        return final

    assert run(scenario())["status"] == "completed"


def test_idempotency_key_never_resubmits(live_bridge: LiveBridge) -> None:
    async def scenario() -> tuple[str, str, int]:
        device_id, credential = await pair_device(live_bridge)
        ws = await open_device(live_bridge, device_id, credential)
        await send_state(ws, "t1", "READY")
        async with httpx.AsyncClient(base_url=live_bridge.base) as http:
            tab = await find_tab_id(http, live_bridge)
            a = await post_request(http, live_bridge, tab, "same", "dup-key")
            b = await post_request(http, live_bridge, tab, "same", "dup-key")
            msg = await recv_json(ws)
            await ws.send(
                json.dumps(
                    {
                        "type": "result",
                        "request_id": msg["request_id"],
                        "status": "completed",
                        "text": "x",
                    }
                )
            )
            await poll_until_done(http, live_bridge, tab, a["request_id"])
            extra = 0
            try:
                await recv_json(ws, timeout=0.4)
                extra = 1
            except TimeoutError:
                pass
        await ws.close()
        return a["request_id"], b["request_id"], extra

    a_id, b_id, extra = run(scenario())
    assert a_id == b_id
    assert extra == 0


def test_generation_timeout_cancels_on_device(live_bridge: LiveBridge) -> None:
    async def scenario() -> tuple[dict[str, Any], dict[str, Any]]:
        device_id, credential = await pair_device(live_bridge)
        ws = await open_device(live_bridge, device_id, credential)
        await send_state(ws, "t1", "READY")
        async with httpx.AsyncClient(base_url=live_bridge.base) as http:
            tab = await find_tab_id(http, live_bridge)
            req = await post_request(
                http, live_bridge, tab, "slow", "k-timeout", timeout_s=0.5
            )
            dispatched = await recv_json(ws)
            cancel = await recv_json(ws, timeout=5)
            assert cancel == {"type": "cancel", "request_id": dispatched["request_id"]}
            final = await poll_until_done(http, live_bridge, tab, req["request_id"])
        await ws.close()
        return final, cancel

    final, _ = run(scenario())
    assert final["status"] == "failed"
    assert final["error_code"] == "GENERATION_TIMEOUT"


def test_queued_request_can_be_cancelled_before_dispatch(
    live_bridge: LiveBridge,
) -> None:
    async def scenario() -> tuple[dict[str, Any], int]:
        device_id, credential = await pair_device(live_bridge)
        ws = await open_device(live_bridge, device_id, credential)
        await send_state(ws, "t1", "READY")
        async with httpx.AsyncClient(base_url=live_bridge.base) as http:
            tab = await find_tab_id(http, live_bridge)
            first = await post_request(http, live_bridge, tab, "running", "k-a")
            queued = await post_request(http, live_bridge, tab, "never sent", "k-b")
            m1 = await recv_json(ws)
            cancel_resp = await http.post(
                f"/api/tabs/{tab}/requests/{queued['request_id']}/cancel",
                headers=_auth(live_bridge),
            )
            assert cancel_resp.status_code == 200
            cancelled = dict(cancel_resp.json())
            await ws.send(
                json.dumps(
                    {
                        "type": "result",
                        "request_id": m1["request_id"],
                        "status": "completed",
                        "text": "r",
                    }
                )
            )
            await poll_until_done(http, live_bridge, tab, first["request_id"])
            extra = 0
            try:
                await recv_json(ws, timeout=0.4)
                extra = 1
            except TimeoutError:
                pass
        await ws.close()
        return cancelled, extra

    cancelled, extra = run(scenario())
    assert cancelled["status"] == "cancelled"
    assert extra == 0, "a cancelled queued request must never reach the page"


def test_disconnect_mid_request_reports_uncertain_submission(
    live_bridge: LiveBridge,
) -> None:
    async def scenario() -> tuple[dict[str, Any], int]:
        device_id, credential = await pair_device(live_bridge)
        ws = await open_device(live_bridge, device_id, credential)
        await send_state(ws, "t1", "READY")
        async with httpx.AsyncClient(base_url=live_bridge.base) as http:
            tab = await find_tab_id(http, live_bridge)
            req = await post_request(http, live_bridge, tab, "risky", "k-uncertain")
            await recv_json(ws)
            await ws.close()
            final = await poll_until_done(http, live_bridge, tab, req["request_id"])
            # Reconnect: the bridge must not resubmit the prompt automatically.
            ws2 = await open_device(live_bridge, device_id, credential)
            await send_state(ws2, "t1", "READY")
            extra = 0
            try:
                await recv_json(ws2, timeout=0.4)
                extra = 1
            except TimeoutError:
                pass
            await ws2.close()
        return final, extra

    final, extra = run(scenario())
    assert final["status"] == "failed"
    assert final["error_code"] == "UNCERTAIN_SUBMISSION"
    assert extra == 0


def test_result_from_another_device_is_ignored(live_bridge: LiveBridge) -> None:
    async def scenario() -> dict[str, Any]:
        dev_a, cred_a = await pair_device(live_bridge)
        dev_b, cred_b = await pair_device(live_bridge)
        ws_a = await open_device(live_bridge, dev_a, cred_a)
        ws_b = await open_device(live_bridge, dev_b, cred_b)
        await send_state(ws_a, "t1", "READY")
        async with httpx.AsyncClient(base_url=live_bridge.base) as http:
            tab = await find_tab_id(http, live_bridge)
            req = await post_request(
                http, live_bridge, tab, "for A", "k-owner", timeout_s=1.0
            )
            msg = await recv_json(ws_a)
            await ws_b.send(
                json.dumps(
                    {
                        "type": "result",
                        "request_id": msg["request_id"],
                        "status": "completed",
                        "text": "spoofed",
                    }
                )
            )
            final = await poll_until_done(http, live_bridge, tab, req["request_id"])
        await ws_a.close()
        await ws_b.close()
        return final

    final = run(scenario())
    assert final["text"] != "spoofed"
    assert final["status"] == "failed"  # the owner never answered, so it times out


def test_provider_error_is_reported_with_known_code_only(
    live_bridge: LiveBridge,
) -> None:
    async def scenario() -> dict[str, Any]:
        device_id, credential = await pair_device(live_bridge)
        ws = await open_device(live_bridge, device_id, credential)
        await send_state(ws, "t1", "READY")
        async with httpx.AsyncClient(base_url=live_bridge.base) as http:
            tab = await find_tab_id(http, live_bridge)
            req = await post_request(http, live_bridge, tab, "boom", "k-err")
            msg = await recv_json(ws)
            await ws.send(
                json.dumps(
                    {
                        "type": "result",
                        "request_id": msg["request_id"],
                        "status": "failed",
                        "error_code": "SELECTOR_NOT_FOUND",
                    }
                )
            )
            final = await poll_until_done(http, live_bridge, tab, req["request_id"])
            req2 = await post_request(http, live_bridge, tab, "boom2", "k-err2")
            msg2 = await recv_json(ws)
            await ws.send(
                json.dumps(
                    {
                        "type": "result",
                        "request_id": msg2["request_id"],
                        "status": "failed",
                        "error_code": "MADE_UP_CODE",
                    }
                )
            )
            final2 = await poll_until_done(http, live_bridge, tab, req2["request_id"])
        await ws.close()
        return {"a": final, "b": final2}

    out = run(scenario())
    assert out["a"]["error_code"] == "SELECTOR_NOT_FOUND"
    assert out["b"]["error_code"] == "PROVIDER_ERROR"


def test_unknown_tab_and_request_return_404(live_bridge: LiveBridge) -> None:
    async def scenario() -> tuple[int, int]:
        async with httpx.AsyncClient(base_url=live_bridge.base) as http:
            a = await http.post(
                "/api/tabs/tab_missing/requests",
                headers=_auth(live_bridge),
                json={"prompt": "x", "idempotency_key": "k"},
            )
            b = await http.get(
                "/api/tabs/tab_missing/requests/req_missing", headers=_auth(live_bridge)
            )
            return a.status_code, b.status_code

    assert run(scenario()) == (404, 404)


def test_prompt_length_is_bounded(live_bridge: LiveBridge) -> None:
    async def scenario() -> int:
        async with httpx.AsyncClient(base_url=live_bridge.base) as http:
            resp = await http.post(
                "/api/tabs/tab_x/requests",
                headers=_auth(live_bridge),
                json={"prompt": "x" * 20_001, "idempotency_key": "k"},
            )
            return resp.status_code

    assert run(scenario()) == 422
