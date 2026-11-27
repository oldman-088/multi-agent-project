"""Build connections from environment variables. Secrets are read from the environment only.

- OLLAMA_ENABLED=1 enables Ollama. OLLAMA_BASE_URL (default http://127.0.0.1:11434), OLLAMA_MODEL (required).
- OPENAI_COMPAT_ENABLED=1 enables the OpenAI-compatible endpoint. It is OFF by default.
  Requires OPENAI_COMPAT_BASE_URL, OPENAI_COMPAT_MODEL and OPENAI_COMPAT_API_KEY.
- BROWSER_BRIDGE_URL enables the browser session. Requires BROWSER_BRIDGE_API_TOKEN
  (at least 32 characters) and BROWSER_BRIDGE_TAB_ID.

Error messages name the missing variables, never their values.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.connections.base import ModelConnection
from app.connections.browser_session import BrowserSessionConnection
from app.connections.ollama import OllamaConnection
from app.connections.openai_compatible import OpenAICompatibleConnection

_TRUE = frozenset({"1", "true", "yes", "on"})
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"


def _enabled(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in _TRUE


def _missing(env: Mapping[str, str], names: tuple[str, ...]) -> list[str]:
    return [name for name in names if not env.get(name, "").strip()]


def build_connections(env: Mapping[str, str]) -> list[ModelConnection]:
    connections: list[ModelConnection] = []

    if _enabled(env, "OLLAMA_ENABLED"):
        absent = _missing(env, ("OLLAMA_MODEL",))
        if absent:
            raise ValueError(f"Ollama is enabled but {', '.join(absent)} is not set")
        connections.append(
            OllamaConnection(
                connection_id="ollama",
                base_url=env.get("OLLAMA_BASE_URL", "").strip() or DEFAULT_OLLAMA_URL,
                model=env["OLLAMA_MODEL"].strip(),
            )
        )

    if _enabled(env, "OPENAI_COMPAT_ENABLED"):
        required = (
            "OPENAI_COMPAT_BASE_URL",
            "OPENAI_COMPAT_MODEL",
            "OPENAI_COMPAT_API_KEY",
        )
        absent = _missing(env, required)
        if absent:
            raise ValueError(
                f"OpenAI-compatible endpoint is enabled but {', '.join(absent)} not set"
            )
        connections.append(
            OpenAICompatibleConnection(
                connection_id="openai_compatible",
                base_url=env["OPENAI_COMPAT_BASE_URL"].strip(),
                model=env["OPENAI_COMPAT_MODEL"].strip(),
                api_key=env["OPENAI_COMPAT_API_KEY"].strip(),
            )
        )

    if env.get("BROWSER_BRIDGE_URL", "").strip():
        browser_required = ("BROWSER_BRIDGE_API_TOKEN", "BROWSER_BRIDGE_TAB_ID")
        absent = _missing(env, browser_required)
        if absent:
            raise ValueError(
                f"browser session is configured but {', '.join(absent)} not set"
            )
        if len(env["BROWSER_BRIDGE_API_TOKEN"].strip()) < 32:
            raise ValueError("BROWSER_BRIDGE_API_TOKEN must be at least 32 characters")
        connections.append(
            BrowserSessionConnection(
                connection_id="browser_session",
                base_url=env["BROWSER_BRIDGE_URL"].strip(),
                api_token=env["BROWSER_BRIDGE_API_TOKEN"].strip(),
                tab_id=env["BROWSER_BRIDGE_TAB_ID"].strip(),
            )
        )

    return connections
