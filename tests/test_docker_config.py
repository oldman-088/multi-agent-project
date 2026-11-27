"""Tests for the Docker deployment configuration.

These validate the deployment deliverables statically (without needing Docker):
the compose file wires backend + frontend + bridge, the Dockerfiles exist, and
.env.example documents variables without real values.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "docker-compose.yml"
ENV_EXAMPLE_PATH = ROOT / ".env.example"
DOCKER_DIR = ROOT / "infrastructure" / "docker"


def _compose() -> dict:
    with COMPOSE_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_compose_defines_all_three_services() -> None:
    compose = _compose()
    services = compose["services"]
    assert set(services) >= {"backend", "frontend", "bridge"}


def test_compose_dockerfiles_exist() -> None:
    compose = _compose()
    for name, dockerfile in (
        ("backend", "Dockerfile.backend"),
        ("frontend", "Dockerfile.frontend"),
        ("bridge", "Dockerfile.bridge"),
    ):
        path = dockerfile_path = DOCKER_DIR / dockerfile
        assert dockerfile_path.is_file(), f"{path} is missing"
        service = compose["services"][name]
        assert service["build"]["dockerfile"] == str(
            Path("infrastructure/docker") / dockerfile
        )


def test_compose_contexts_exist() -> None:
    compose = _compose()
    expected = {
        "backend": "backend",
        "bridge": "integrations/browser-bridge",
        "frontend": "frontend",
    }
    for name, context in expected.items():
        assert compose["services"][name]["build"]["context"] == f"./{context}"
        assert (ROOT / context).is_dir()


def test_backend_port_is_published_for_health() -> None:
    compose = _compose()
    # Backend must be reachable so /health can be probed.
    assert any("8000" in port for port in compose["services"]["backend"]["ports"])


def test_bridge_is_not_published_to_host() -> None:
    """The bridge must stay internal: reachable by containers, not the host."""
    compose = _compose()
    bridge = compose["services"]["bridge"]
    assert "ports" not in bridge or not bridge.get("ports")


def test_env_example_documents_required_variables() -> None:
    text = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    for key in (
        "APP_VERSION",
        "BACKEND_PORT",
        "BRIDGE_HOST",
        "BRIDGE_PORT",
        "BRIDGE_ALLOWED_ORIGINS",
        "BRIDGE_PAIR_TOKEN",
        "FRONTEND_PORT",
    ):
        assert f"{key}=" in text, f"{key} is missing from .env.example"


# Characters typical of a real secret (long, opaque, base64/hex-ish runs).
import re

_SECRET_RUN = re.compile(r"[A-Za-z0-9_\-]{40,}")
_SECRET_KEYS = ("TOKEN", "KEY", "PASSWORD", "SECRET", "CREDENTIAL")
_PLACEHOLDERS = ("change-me", "placeholder", "xxx", "<", "${")


def test_env_example_has_no_real_secrets() -> None:
    text = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # No opaque, long secret-like run anywhere.
        assert not _SECRET_RUN.search(value), f"secret-like value in .env.example: {line}"
        # Anything that looks like a secret key must hold an explicit placeholder.
        if any(marker in key.upper() for marker in _SECRET_KEYS):
            assert any(value.startswith(p) for p in _PLACEHOLDERS), (
                f"{key} is not a placeholder: {value}"
            )
    # The pair token must be an explicit placeholder.
    assert "BRIDGE_PAIR_TOKEN=change-me" in text


def test_deployment_doc_exists() -> None:
    doc = ROOT / "docs" / "DEPLOYMENT.md"
    assert doc.is_file()
    content = doc.read_text(encoding="utf-8").lower()
    assert "docker compose up" in content
    assert "/health" in content
