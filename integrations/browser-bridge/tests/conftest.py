from __future__ import annotations

import socket
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import uvicorn

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from app import BridgeSettings, create_app
from pairing import digest

API_TOKEN = "test-api-token-" + "x" * 32
ALLOWED_ORIGIN = "http://127.0.0.1:8787"


@dataclass(frozen=True)
class LiveBridge:
    base: str
    ws_url: str
    token: str
    origin: str


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def live_bridge() -> Iterator[LiveBridge]:
    """Run the real bridge app on a free loopback port for one test."""
    port = _free_port()
    settings = BridgeSettings(
        api_token_digest=digest(API_TOKEN),
        allowed_origins=frozenset({ALLOWED_ORIGIN}),
    )
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings),
            host="127.0.0.1",
            port=port,
            log_level="warning",
            lifespan="off",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("bridge did not start")
        time.sleep(0.02)
    try:
        yield LiveBridge(
            base=f"http://127.0.0.1:{port}",
            ws_url=f"ws://127.0.0.1:{port}/ws/userscript",
            token=API_TOKEN,
            origin=ALLOWED_ORIGIN,
        )
    finally:
        server.should_exit = True
        thread.join(timeout=10)
