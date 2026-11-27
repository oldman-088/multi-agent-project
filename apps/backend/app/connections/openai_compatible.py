"""OpenAI-compatible HTTP endpoint. Closed by default (see factory.py).

The API key is passed in at construction (read from an environment variable by the
factory) and is never stored in repr, logs or health details.
"""

from __future__ import annotations

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
    Usage,
)


class OpenAICompatibleConnection:
    kind: ConnectionKind = "api"

    def __init__(
        self,
        *,
        connection_id: str,
        base_url: str,
        model: str,
        api_key: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.id = connection_id
        self.model = model
        self._api_key = api_key
        self._http = http or httpx.AsyncClient(
            base_url=base_url, timeout=httpx.Timeout(120.0, connect=5.0)
        )

    def __repr__(self) -> str:  # never show the key
        return f"OpenAICompatibleConnection(id={self.id!r}, model={self.model!r})"

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def capabilities(self) -> ConnectionCapabilities:
        return ConnectionCapabilities(
            streaming="not_verified",  # not implemented here; stream() raises UnsupportedOperation
            native_tool_calling="not_verified",
            structured_output="not_verified",
            multimodal_input="not_verified",
            usage_reporting="partial",  # reported only when the endpoint includes a usage object
            agent_mode="unsupported",
            max_concurrency=None,
            max_prompt_characters=None,
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        payload = {"model": self.model, "messages": messages, "stream": False}
        try:
            resp = await self._http.post(
                "/chat/completions", headers=self._headers, json=payload
            )
        except httpx.HTTPError as exc:
            raise ConnectionRequestFailed(
                "PROVIDER_UNREACHABLE", type(exc).__name__
            ) from exc
        if resp.status_code in (401, 403):
            raise ConnectionRequestFailed(
                "PROVIDER_AUTH", f"endpoint answered {resp.status_code}"
            )
        if resp.status_code != 200:
            raise ConnectionRequestFailed(
                "PROVIDER_ERROR", f"endpoint answered {resp.status_code}"
            )
        body = _as_dict(resp.json())
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ConnectionRequestFailed("PROVIDER_ERROR", "response has no choices")
        message = _as_dict(_as_dict(choices[0]).get("message", {}))
        content = message.get("content")
        if not isinstance(content, str):
            raise ConnectionRequestFailed(
                "PROVIDER_ERROR", "response has no text content"
            )
        usage: Usage | None = None
        usage_obj = body.get("usage")
        if isinstance(usage_obj, dict):
            prompt_t = usage_obj.get("prompt_tokens")
            completion_t = usage_obj.get("completion_tokens")
            if isinstance(prompt_t, int) and isinstance(completion_t, int):
                usage = Usage(prompt_tokens=prompt_t, completion_tokens=completion_t)
        return GenerationResult(
            text=content,
            connection_id=self.id,
            usage=usage,
            model=str(body.get("model") or self.model),
        )

    def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        raise UnsupportedOperation(
            "streaming is not implemented for OpenAI-compatible endpoints yet"
        )

    async def health(self) -> ConnectionHealth:
        try:
            resp = await self._http.get("/models", headers=self._headers, timeout=5.0)
        except httpx.HTTPError:
            return ConnectionHealth(
                status="offline", detail="endpoint is not reachable"
            )
        if resp.status_code in (401, 403):
            return ConnectionHealth(
                status="degraded", detail="endpoint rejected the API key"
            )
        if resp.status_code != 200:
            return ConnectionHealth(
                status="offline", detail=f"endpoint answered {resp.status_code}"
            )
        return ConnectionHealth(status="ok", detail="endpoint reachable")

    async def aclose(self) -> None:
        await self._http.aclose()


def _as_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConnectionRequestFailed(
            "PROVIDER_ERROR", "unexpected provider response shape"
        )
    return value
