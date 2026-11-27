#!/usr/bin/env python3
"""Install the minimal fixture applications used by the container smoke test.

The container images build the real application slices.  While those slices
are not merged yet there is nothing to build, so this script copies a very
small stand-in into the expected location:

    backend   ->  backend/                      (FastAPI app with GET /health)
    frontend  ->  apps/web/                     (static bundle written to dist/)
    bridge    ->  integrations/browser-bridge/  (FastAPI app with GET /health)

A fixture is only installed when the matching real slice is missing, so the
smoke test always prefers the real application.

Usage::

    python tests/fixtures/dockerstack/install_fixtures.py [--root .] [--force]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parent


def _has_build_script(package_json: Path) -> bool:
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    scripts = data.get("scripts")
    return isinstance(scripts, dict) and "build" in scripts


def backend_present(root: Path) -> bool:
    return any(
        (root / relative / "app" / "main.py").is_file()
        for relative in ("backend", "apps/backend")
    )


def frontend_present(root: Path) -> bool:
    return any(
        _has_build_script(candidate)
        for candidate in (root / "apps" / "web" / "package.json", root / "package.json")
    )


def bridge_present(root: Path) -> bool:
    return any(
        (root / "integrations" / "browser-bridge" / relative).is_file()
        for relative in ("src/app.py", "app.py")
    )


ROLES: tuple[tuple[str, str, str, object], ...] = (
    ("backend", "backend", "backend", backend_present),
    ("frontend", "frontend", "apps/web", frontend_present),
    ("bridge", "bridge", "integrations/browser-bridge", bridge_present),
)


def install(root: Path, force: bool = False) -> int:
    """Install the fixtures that are missing.  Returns the number installed."""

    installed = 0
    for role, fixture, target, present in ROLES:
        if present(root) and not force:
            print(f"{role}: the real slice is present, keeping it")
            continue
        destination = root / target
        source = FIXTURE_ROOT / fixture
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
        installed += 1
        print(f"{role}: installed the fixture into {target}")
    return installed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=str(FIXTURE_ROOT.parents[2]),
        help="repository root (default: the repository this script lives in)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="install the fixtures even when the real slice is present",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    install(root, force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
