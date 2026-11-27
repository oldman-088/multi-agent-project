"""Browser-session connection: talks to one owner-signed-in tab through the local bridge.

Only the bridge's local HTTP API is used here. The backend never touches cookies,
tokens or the provider page itself. Responses carry no usage: `usage` is always None.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.connections.base import (
    ConnectionCapabilities,
    ConnectionHealth,
    ConnectionKind,
    ConnectionRequestFailed,
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    UnsupportedOperation,
    compose_prompt,
)

MAX_PROMPT_CHARS = 20_000
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
GRACE_S = 10.0


class BrowserSessionConnection:
    kind: ConnectionKind = "browser_session"

    def __init__(
        self,
        *,
        connection_id: str,
        base_url: str,
        api_token: str,
        tab_id: str,
        http: httpx.AsyncClient | None = None,
        poll_interval_s: float = 0.25,
        grace_s: float = GRACE_S,
    ) -> None:
        self.id = connection_id
        self._tab_id = tab_id
        self._headers = {"Authorization": f"Bearer {api_token}"}
        self._http = http or httpx.AsyncClient(base_url=base_url, timeout=10.0)
        self._poll_interval_s = poll_interval_s
        self._grace_s = grace_s

    def __repr__(self) -> str:  # never show the bearer token
        return f"BrowserSessionConnection(id={self.id!r}, kind={self.kind!r})"

    async def capabilities(self) -> ConnectionCapabilities:
        return ConnectionCapabilities(
            streaming="unsupported",  # the bridge streams to the page; this API returns the final text
            native_tool_calling="unsupported",
            structured_output="not_verified",
            multimodal_input="unsupported",
            usage_reporting="unsupported",  # usage is always null for browser sessions
            agent_mode="unsupported",  # agent commands are not exposed through this connection yet
            max_concurrency=1,
            max_prompt_characters=MAX_PROMPT_CHARS,
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        prompt = compose_prompt(request)
        if len(prompt) > MAX_PROMPT_CHARS:
            raise ConnectionRequestFailed(
                "PROMPT_TOO_LONG", f"prompt exceeds {MAX_PROMPT_CHARS} characters"
            )
        key = request.idempotency_key or secrets.token_hex(16)
        try:
            resp = await self._http.post(
                f"/api/tabs/{self._tab_id}/requests",
                headers=self._headers,
                json={
                    "prompt": prompt,
                    "idempotency_key": key,
                    "timeout_s": request.timeout_s,
                },
            )
        except httpx.HTTPError as exc:
            raise ConnectionRequestFailed(
                "BRIDGE_UNREACHABLE", type(exc).__name__
            ) from exc
        if resp.status_code != 202:
            raise ConnectionRequestFailed(
                _bridge_status_code(resp.status_code), "bridge rejected the request"
            )
        request_id = str(_json(resp)["request_id"])

        loop = asyncio.get_running_loop()
        deadline = loop.time() + request.timeout_s + self._grace_s
        while True:
            try:
                poll = await self._http.get(
                    f"/api/tabs/{self._tab_id}/requests/{request_id}",
                    headers=self._headers,
                )
            except httpx.HTTPError as exc:
                raise ConnectionRequestFailed(
                    "BRIDGE_UNREACHABLE", type(exc).__name__
                ) from exc
            if poll.status_code != 200:
                raise ConnectionRequestFailed(
                    _bridge_status_code(poll.status_code), "bridge poll failed"
                )
            state = _json(poll)
            if state["status"] in TERMINAL_STATUSES:
                if state["status"] == "completed":
                    return GenerationResult(
                        text=str(state["text"]), connection_id=self.id, usage=None
                    )
                code = state.get("error_code") or "PROVIDER_ERROR"
                raise ConnectionRequestFailed(str(code), f"request {state['status']}")
            if loop.time() > deadline:
                raise ConnectionRequestFailed("TIMEOUT", "polling deadline exceeded")
            await asyncio.sleep(self._poll_interval_s)

    def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        raise UnsupportedOperation(
            "browser_session connections do not stream through the bridge API yet"
        )

    async def health(self) -> ConnectionHealth:
        try:
            resp = await self._http.get("/api/tabs", headers=self._headers)
        except httpx.HTTPError:
            return ConnectionHealth(status="offline", detail="bridge unreachable")
        if resp.status_code in (401, 403):
            return ConnectionHealth(
                status="offline", detail="bridge rejected the API token"
            )
        if resp.status_code != 200:
            return ConnectionHealth(
                status="offline", detail=f"bridge answered {resp.status_code}"
            )
        tabs = resp.json()
        tab = next((t for t in tabs if t.get("tab_id") == self._tab_id), None)
        if tab is None:
            return ConnectionHealth(
                status="offline", detail="configured tab is not connected"
            )
        state = str(tab["state"])
        if state == "READY":
            return ConnectionHealth(status="ok", detail="tab ready")
        if state in {"BUSY", "WAITING_FOR_USER", "RATE_LIMITED"}:
            return ConnectionHealth(status="degraded", detail=f"tab state {state}")
        return ConnectionHealth(status="offline", detail=f"tab state {state}")

    async def aclose(self) -> None:
        await self._http.aclose()


def _bridge_status_code(status: int) -> str:
    if status in (401, 403):
        return "BRIDGE_AUTH"
    if status == 404:
        return "TAB_NOT_FOUND"
    if status == 503:
        return "BRIDGE_NOT_CONFIGURED"
    return "BRIDGE_ERROR"


def _json(resp: httpx.Response) -> dict[str, Any]:
    data = resp.json()
    if not isinstance(data, dict):
        raise ConnectionRequestFailed("BRIDGE_ERROR", "unexpected bridge response")
    return data
