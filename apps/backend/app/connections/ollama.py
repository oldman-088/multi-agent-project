"""Ollama connection (local model server). Usage comes only from Ollama's own counters."""

from __future__ import annotations

import json
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
    Usage,
)


class OllamaConnection:
    kind: ConnectionKind = "local"

    def __init__(
        self,
        *,
        connection_id: str,
        base_url: str,
        model: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.id = connection_id
        self.model = model
        self._http = http or httpx.AsyncClient(
            base_url=base_url, timeout=httpx.Timeout(300.0, connect=5.0)
        )

    async def capabilities(self) -> ConnectionCapabilities:
        return ConnectionCapabilities(
            streaming="supported",
            native_tool_calling="not_verified",  # depends on the pulled model; not tested here
            structured_output="not_verified",
            multimodal_input="not_verified",
            usage_reporting="partial",  # counters arrive only on the final message of a response
            agent_mode="unsupported",
            max_concurrency=None,
            max_prompt_characters=None,
        )

    def _messages(self, request: GenerationRequest) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        return messages

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        payload = {
            "model": self.model,
            "messages": self._messages(request),
            "stream": False,
        }
        try:
            resp = await self._http.post("/api/chat", json=payload)
        except httpx.HTTPError as exc:
            raise ConnectionRequestFailed(
                "PROVIDER_UNREACHABLE", type(exc).__name__
            ) from exc
        if resp.status_code != 200:
            raise ConnectionRequestFailed(
                "PROVIDER_ERROR", f"ollama answered {resp.status_code}"
            )
        body = _as_dict(resp.json())
        message = _as_dict(body.get("message", {}))
        return GenerationResult(
            text=str(message.get("content", "")),
            connection_id=self.id,
            usage=_usage(body),
            model=self.model,
        )

    async def stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[GenerationChunk]:
        payload = {
            "model": self.model,
            "messages": self._messages(request),
            "stream": True,
        }
        try:
            async with self._http.stream("POST", "/api/chat", json=payload) as resp:
                if resp.status_code != 200:
                    raise ConnectionRequestFailed(
                        "PROVIDER_ERROR", f"ollama answered {resp.status_code}"
                    )
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = _as_dict(json.loads(line))
                    text = str(_as_dict(chunk.get("message", {})).get("content", ""))
                    if chunk.get("done") is True:
                        yield GenerationChunk(text=text, done=True, usage=_usage(chunk))
                        return
                    if text:
                        yield GenerationChunk(text=text)
        except httpx.HTTPError as exc:
            raise ConnectionRequestFailed(
                "PROVIDER_UNREACHABLE", type(exc).__name__
            ) from exc

    async def health(self) -> ConnectionHealth:
        try:
            resp = await self._http.get("/api/tags", timeout=5.0)
        except httpx.HTTPError:
            return ConnectionHealth(status="offline", detail="ollama is not reachable")
        if resp.status_code != 200:
            return ConnectionHealth(
                status="offline", detail=f"ollama answered {resp.status_code}"
            )
        models = _as_dict(resp.json()).get("models", [])
        names = {
            str(_as_dict(m).get("name", "")) for m in models if isinstance(m, dict)
        }
        if self.model in names or f"{self.model}:latest" in names:
            return ConnectionHealth(status="ok", detail="model available")
        return ConnectionHealth(
            status="degraded", detail="configured model is not pulled"
        )

    async def aclose(self) -> None:
        await self._http.aclose()


def _usage(body: dict[str, Any]) -> Usage | None:
    prompt = body.get("prompt_eval_count")
    completion = body.get("eval_count")
    if isinstance(prompt, int) and isinstance(completion, int):
        return Usage(prompt_tokens=prompt, completion_tokens=completion)
    return None


def _as_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConnectionRequestFailed(
            "PROVIDER_ERROR", "unexpected provider response shape"
        )
    return value
