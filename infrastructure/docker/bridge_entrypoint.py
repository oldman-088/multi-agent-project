#!/usr/bin/env python3
"""Start the Local Browser Bridge inside a container.

The bridge application binds ``127.0.0.1`` and refuses every other address
(docs/SPEC.md section 3.2): it must never be reachable from the network of
the machine it runs on.

Inside a container the picture is slightly different.  The published port has
to be reachable from the host loopback (the userscript runs in the owner's
own browser) and from the other services of the compose stack, which is only
possible when the process listens on all addresses *of the container network
namespace*.  The exposure is unchanged from the outside: docker compose
publishes the bridge port on ``127.0.0.1`` only, so nothing outside the
machine can reach it, and every client still has to pass the bridge's own
pairing, origin and bearer-token checks.

This entry point does not modify the bridge: it imports the application's own
factory and settings, so the pairing store, the origin allow-list and the
token verification stay exactly as the bridge slice implements them.  When the
factory cannot be imported the bridge's own ``__main__`` is executed instead,
which keeps the strict loopback bind.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_PORT = "8765"


def _app_dir() -> Path:
    return Path(os.environ.get("BRIDGE_APP_DIR", "/app"))


def _run_factory(app_dir: Path) -> int:
    """Start uvicorn with the bridge's own application factory."""

    sys.path.insert(0, str(app_dir))
    from app import BridgeSettings, create_app  # noqa: PLC0415 - late import on purpose

    settings = BridgeSettings.from_env(os.environ)
    host = os.environ.get("BRIDGE_BIND_HOST", DEFAULT_BIND_HOST)
    port = int(os.environ.get("BRIDGE_PORT", DEFAULT_PORT))

    import uvicorn  # noqa: PLC0415 - late import on purpose

    uvicorn.run(create_app(settings), host=host, port=port, log_level="warning")
    return 0


def _run_application(app_dir: Path) -> int:
    """Fall back to the bridge's own entry point (strict loopback bind)."""

    entry = app_dir / "app.py"
    runpy.run_path(str(entry), run_name="__main__")
    return 0


def main() -> int:
    app_dir = _app_dir()
    if not (app_dir / "app.py").is_file():
        print(
            f"bridge_entrypoint: no bridge application found in {app_dir}",
            file=sys.stderr,
        )
        return 1
    try:
        return _run_factory(app_dir)
    except ImportError as exc:
        print(
            f"bridge_entrypoint: falling back to the bridge entry point ({exc})",
            file=sys.stderr,
        )
        return _run_application(app_dir)


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
