"""Tests for the ModelConnection layer: honest capabilities, usage never invented,
env-only secrets, OpenAI-compatible endpoint closed by default."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from app.connections import (
    BrowserSessionConnection,
    ConnectionCapabilities,
    ConnectionRequestFailed,
    GenerationRequest,
    ModelConnection,
    OllamaConnection,
    OpenAICompatibleConnection,
    UnsupportedOperation,
    Usage,
    build_connections,
)
from app.connections.base import CAPABILITY_VALUES

Handler = Callable[[httpx.Request], httpx.Response]
TOKEN = "b" * 40
API_KEY = "fake-key-for-tests-" + "k" * 30  # not a credential; test value only


def mock_client(
    handler: Handler, base: str = "http://provider.test"
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=base)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


CAP_FIELDS = (
    "streaming",
    "native_tool_calling",
    "structured_output",
    "multimodal_input",
    "usage_reporting",
    "agent_mode",
)


def assert_honest_caps(caps: ConnectionCapabilities) -> None:
    for name in CAP_FIELDS:
        assert getattr(caps, name) in CAPABILITY_VALUES, name
    assert caps.max_concurrency is None or caps.max_concurrency >= 1


# ----- capability model --------------------------------------------------------


def test_capability_values_are_restricted() -> None:
    assert CAPABILITY_VALUES == {"supported", "partial", "unsupported", "not_verified"}
    with pytest.raises(ValueError):
        ConnectionCapabilities(streaming="maybe")  # type: ignore[arg-type]


def test_default_capabilities_are_not_verified_not_supported() -> None:
    caps = ConnectionCapabilities()
    assert caps.native_tool_calling == "not_verified"
    assert caps.usage_reporting == "not_verified"
    assert caps.max_concurrency is None


def test_all_connections_satisfy_protocol_and_declare_honest_capabilities() -> None:
    conns: list[ModelConnection] = [
        OllamaConnection(
            connection_id="o",
            base_url="http://ollama.test",
            model="m",
            http=mock_client(lambda r: httpx.Response(500)),
        ),
        OpenAICompatibleConnection(
            connection_id="x",
            base_url="http://api.test",
            model="m",
            api_key=API_KEY,
            http=mock_client(lambda r: httpx.Response(500)),
        ),
        BrowserSessionConnection(
            connection_id="b",
            base_url="http://bridge.test",
            api_token=TOKEN,
            tab_id="tab_1",
            http=mock_client(lambda r: httpx.Response(500)),
        ),
    ]
    for conn in conns:
        assert isinstance(conn, ModelConnection)
        assert_honest_caps(run(conn.capabilities()))


def test_browser_session_never_claims_usage_or_streaming() -> None:
    conn = BrowserSessionConnection(
        connection_id="b",
        base_url="http://bridge.test",
        api_token=TOKEN,
        tab_id="t",
        http=mock_client(lambda r: httpx.Response(500)),
    )
    caps = run(conn.capabilities())
    assert caps.usage_reporting == "unsupported"
    assert caps.streaming == "unsupported"
    assert caps.native_tool_calling == "unsupported"
    assert caps.agent_mode == "unsupported"
    assert caps.max_concurrency == 1


def test_ollama_usage_is_partial_and_streaming_supported() -> None:
    conn = OllamaConnection(
        connection_id="o",
        base_url="http://ollama.test",
        model="m",
        http=mock_client(lambda r: httpx.Response(500)),
    )
    caps = run(conn.capabilities())
    assert caps.streaming == "supported"
    assert caps.usage_reporting == "partial"
    assert caps.native_tool_calling == "not_verified"


# ----- Ollama ------------------------------------------------------------------


def test_ollama_generate_reports_provider_counters_only() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "hi there"},
                "done": True,
                "prompt_eval_count": 7,
                "eval_count": 3,
            },
        )

    conn = OllamaConnection(
        connection_id="o",
        base_url="http://ollama.test",
        model="llama",
        http=mock_client(handler),
    )
    result = run(conn.generate(GenerationRequest(prompt="hello", system="be brief")))
    assert result.text == "hi there"
    assert result.usage == Usage(prompt_tokens=7, completion_tokens=3)
    assert seen["path"] == "/api/chat"
    assert seen["body"]["stream"] is False
    assert seen["body"]["messages"][0] == {"role": "system", "content": "be brief"}


def test_ollama_usage_is_none_when_counters_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"message": {"content": "no counters"}, "done": True}
        )

    conn = OllamaConnection(
        connection_id="o",
        base_url="http://ollama.test",
        model="m",
        http=mock_client(handler),
    )
    result = run(conn.generate(GenerationRequest(prompt="x")))
    assert result.usage is None


def test_ollama_stream_yields_deltas_then_final_usage() -> None:
    body = "\n".join(
        [
            json.dumps({"message": {"content": "Hel"}, "done": False}),
            json.dumps({"message": {"content": "lo"}, "done": False}),
            json.dumps(
                {
                    "message": {"content": ""},
                    "done": True,
                    "prompt_eval_count": 2,
                    "eval_count": 1,
                }
            ),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, content=body.encode())

    async def collect() -> list[Any]:
        conn = OllamaConnection(
            connection_id="o",
            base_url="http://ollama.test",
            model="m",
            http=mock_client(handler),
        )
        return [chunk async for chunk in conn.stream(GenerationRequest(prompt="x"))]

    chunks = run(collect())
    assert [c.text for c in chunks] == ["Hel", "lo", ""]
    assert chunks[-1].done is True
    assert chunks[-1].usage == Usage(prompt_tokens=2, completion_tokens=1)
    assert all(c.usage is None for c in chunks[:-1])


def test_ollama_errors_map_to_stable_codes() -> None:
    def server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal details")

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async def attempt(handler: Handler) -> str:
        conn = OllamaConnection(
            connection_id="o",
            base_url="http://ollama.test",
            model="m",
            http=mock_client(handler),
        )
        try:
            await conn.generate(GenerationRequest(prompt="x"))
        except ConnectionRequestFailed as exc:
            return exc.code
        raise AssertionError("expected failure")

    assert run(attempt(server_error)) == "PROVIDER_ERROR"
    assert run(attempt(unreachable)) == "PROVIDER_UNREACHABLE"


def test_ollama_health_states() -> None:
    def tags(models: list[str]) -> Handler:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"models": [{"name": m} for m in models]})

        return handler

    async def health(handler: Handler) -> tuple[str, str]:
        conn = OllamaConnection(
            connection_id="o",
            base_url="http://ollama.test",
            model="llama3",
            http=mock_client(handler),
        )
        h = await conn.health()
        return h.status, h.detail

    assert run(health(tags(["llama3:latest"])))[0] == "ok"
    assert run(health(tags(["other:latest"])))[0] == "degraded"

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    assert run(health(down))[0] == "offline"


# ----- OpenAI-compatible endpoint ---------------------------------------------


def test_openai_compatible_sends_bearer_key_and_reports_usage_when_present() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["path"] = request.url.path
        return httpx.Response(
            200,
            json={
                "model": "gpt-x",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 2,
                    "total_tokens": 6,
                },
            },
        )

    conn = OpenAICompatibleConnection(
        connection_id="x",
        base_url="http://api.test/v1",
        model="gpt-x",
        api_key=API_KEY,
        http=mock_client(handler, "http://api.test/v1"),
    )
    result = run(conn.generate(GenerationRequest(prompt="hi")))
    assert result.text == "ok"
    assert result.usage == Usage(prompt_tokens=4, completion_tokens=2)
    assert seen["auth"] == f"Bearer {API_KEY}"
    assert seen["path"] == "/v1/chat/completions"


def test_openai_compatible_usage_is_none_when_absent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "no usage here"}}]}
        )

    conn = OpenAICompatibleConnection(
        connection_id="x",
        base_url="http://api.test",
        model="m",
        api_key=API_KEY,
        http=mock_client(handler),
    )
    assert run(conn.generate(GenerationRequest(prompt="x"))).usage is None


def test_openai_compatible_auth_failure_and_stream_unsupported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    conn = OpenAICompatibleConnection(
        connection_id="x",
        base_url="http://api.test",
        model="m",
        api_key=API_KEY,
        http=mock_client(handler),
    )
    with pytest.raises(ConnectionRequestFailed) as info:
        run(conn.generate(GenerationRequest(prompt="x")))
    assert info.value.code == "PROVIDER_AUTH"
    with pytest.raises(UnsupportedOperation):
        run(_first_chunk(conn))


async def _first_chunk(conn: OpenAICompatibleConnection) -> None:
    async for _ in conn.stream(GenerationRequest(prompt="x")):
        pass


def test_openai_compatible_never_exposes_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={})

    conn = OpenAICompatibleConnection(
        connection_id="x",
        base_url="http://api.test",
        model="m",
        api_key=API_KEY,
        http=mock_client(handler),
    )
    assert API_KEY not in repr(conn)
    health = run(conn.health())
    assert API_KEY not in health.detail
    assert health.status == "degraded"


def test_openai_compatible_requires_key() -> None:
    with pytest.raises(ValueError):
        OpenAICompatibleConnection(
            connection_id="x", base_url="http://api.test", model="m", api_key=""
        )


# ----- browser session ---------------------------------------------------------


def _bridge_handler(
    states: list[dict[str, Any]], posted: list[dict[str, Any]]
) -> Handler:
    """Fake bridge: accept POST, then return the scripted states on each GET."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/tabs/tab_1/requests":
            posted.append(json.loads(request.content))
            return httpx.Response(
                202,
                json={
                    "request_id": "req_1",
                    "status": "queued",
                    "text": "",
                    "error_code": None,
                    "queue_position": 0,
                },
            )
        if (
            request.method == "GET"
            and request.url.path == "/api/tabs/tab_1/requests/req_1"
        ):
            state = states.pop(0) if len(states) > 1 else states[0]
            return httpx.Response(
                200,
                json={
                    "request_id": "req_1",
                    "queue_position": 0,
                    "error_code": None,
                    "text": "",
                    **state,
                },
            )
        return httpx.Response(404, json={})

    return handler


def _browser(handler: Handler, grace_s: float = 10.0) -> BrowserSessionConnection:
    return BrowserSessionConnection(
        connection_id="b",
        base_url="http://bridge.test",
        api_token=TOKEN,
        tab_id="tab_1",
        http=mock_client(handler, "http://bridge.test"),
        poll_interval_s=0.01,
        grace_s=grace_s,
    )


def test_browser_generate_polls_until_completed_and_never_invents_usage() -> None:
    posted: list[dict[str, Any]] = []
    states = [
        {"status": "dispatched", "text": ""},
        {"status": "completed", "text": "answer"},
    ]
    conn = _browser(_bridge_handler(states, posted))
    result = run(
        conn.generate(GenerationRequest(prompt="question", idempotency_key="k-1"))
    )
    assert result.text == "answer"
    assert result.usage is None
    assert posted[0]["prompt"] == "question"
    assert posted[0]["idempotency_key"] == "k-1"


def test_browser_generate_maps_bridge_error_codes() -> None:
    posted: list[dict[str, Any]] = []
    conn = _browser(
        _bridge_handler(
            [{"status": "failed", "text": "", "error_code": "SELECTOR_NOT_FOUND"}],
            posted,
        )
    )
    with pytest.raises(ConnectionRequestFailed) as info:
        run(conn.generate(GenerationRequest(prompt="x")))
    assert info.value.code == "SELECTOR_NOT_FOUND"


def test_browser_generate_times_out_on_client_side_deadline() -> None:
    posted: list[dict[str, Any]] = []
    conn = _browser(
        _bridge_handler([{"status": "queued", "text": ""}], posted), grace_s=0.05
    )
    with pytest.raises(ConnectionRequestFailed) as info:
        run(conn.generate(GenerationRequest(prompt="x", timeout_s=0.05)))
    assert info.value.code == "TIMEOUT"


def test_browser_rejects_prompt_over_limit_before_any_network_call() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(500)

    conn = _browser(handler)
    with pytest.raises(ConnectionRequestFailed) as info:
        run(conn.generate(GenerationRequest(prompt="x" * 20_001)))
    assert info.value.code == "PROMPT_TOO_LONG"
    assert calls == []


def test_browser_bad_token_reports_auth_code_without_echoing_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "invalid"})

    conn = _browser(handler)
    with pytest.raises(ConnectionRequestFailed) as info:
        run(conn.generate(GenerationRequest(prompt="x")))
    assert info.value.code == "BRIDGE_AUTH"
    assert TOKEN not in str(info.value)
    assert TOKEN not in repr(conn)


def test_browser_stream_is_unsupported() -> None:
    conn = _browser(lambda r: httpx.Response(500))
    with pytest.raises(UnsupportedOperation):
        run(_first_chunk_browser(conn))


async def _first_chunk_browser(conn: BrowserSessionConnection) -> None:
    async for _ in conn.stream(GenerationRequest(prompt="x")):
        pass


@pytest.mark.parametrize(
    ("tab_state", "expected"),
    [
        ("READY", "ok"),
        ("BUSY", "degraded"),
        ("WAITING_FOR_USER", "degraded"),
        ("DISCONNECTED", "offline"),
    ],
)
def test_browser_health_maps_tab_state(tab_state: str, expected: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "tab_id": "tab_1",
                    "device_id": "dev",
                    "state": tab_state,
                    "agent_state": None,
                    "pending": 0,
                }
            ],
        )

    health = run(_browser(handler).health())
    assert health.status == expected


def test_browser_health_offline_when_tab_missing_or_bridge_down() -> None:
    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    assert run(_browser(empty).health()).status == "offline"
    assert run(_browser(down).health()).status == "offline"


# ----- factory and closed-by-default policy -----------------------------------


def test_no_connections_when_nothing_is_configured() -> None:
    assert build_connections({}) == []


def test_openai_compatible_is_closed_by_default_even_with_key_present() -> None:
    env = {
        "OPENAI_COMPAT_BASE_URL": "http://api.test",
        "OPENAI_COMPAT_MODEL": "m",
        "OPENAI_COMPAT_API_KEY": API_KEY,
    }
    assert all(c.kind != "api" for c in build_connections(env))


def test_openai_compatible_enabled_only_by_explicit_flag_and_env_key() -> None:
    env = {
        "OPENAI_COMPAT_ENABLED": "1",
        "OPENAI_COMPAT_BASE_URL": "http://api.test/v1",
        "OPENAI_COMPAT_MODEL": "m",
        "OPENAI_COMPAT_API_KEY": API_KEY,
    }
    conns = build_connections(env)
    assert [c.id for c in conns] == ["openai_compatible"]
    assert API_KEY not in repr(conns[0])


def test_missing_key_error_names_variable_not_value() -> None:
    env = {
        "OPENAI_COMPAT_ENABLED": "true",
        "OPENAI_COMPAT_BASE_URL": "http://api.test",
        "OPENAI_COMPAT_MODEL": "m",
    }
    with pytest.raises(ValueError) as info:
        build_connections(env)
    assert "OPENAI_COMPAT_API_KEY" in str(info.value)


def test_ollama_enabled_with_default_url_and_model() -> None:
    conns = build_connections({"OLLAMA_ENABLED": "1", "OLLAMA_MODEL": "llama3"})
    assert [c.id for c in conns] == ["ollama"]
    with pytest.raises(ValueError):
        build_connections({"OLLAMA_ENABLED": "1"})


def test_browser_connection_requires_strong_token_and_tab() -> None:
    with pytest.raises(ValueError):
        build_connections(
            {
                "BROWSER_BRIDGE_URL": "http://127.0.0.1:8765",
                "BROWSER_BRIDGE_API_TOKEN": "short",
                "BROWSER_BRIDGE_TAB_ID": "t",
            }
        )
    with pytest.raises(ValueError):
        build_connections(
            {
                "BROWSER_BRIDGE_URL": "http://127.0.0.1:8765",
                "BROWSER_BRIDGE_API_TOKEN": TOKEN,
            }
        )
    conns = build_connections(
        {
            "BROWSER_BRIDGE_URL": "http://127.0.0.1:8765",
            "BROWSER_BRIDGE_API_TOKEN": TOKEN,
            "BROWSER_BRIDGE_TAB_ID": "tab_1",
        }
    )
    assert [c.id for c in conns] == ["browser_session"]
    assert TOKEN not in repr(conns[0])
