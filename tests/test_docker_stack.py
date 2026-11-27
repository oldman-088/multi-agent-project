"""Static validation of the Docker stack (docs/SPEC.md §10, DoD §9).

These tests run **without Docker**: they parse ``docker-compose.yml``,
validate it against the vendored Compose specification schema (after
simulating the ``${VAR:-default}`` interpolation with values from
``.env.example``), and assert the slice contracts that the Dockerfiles,
nginx config, ``.env.example`` and ``docs/DEPLOYMENT.md`` must satisfy.

Runtime verification (``docker compose up`` → ``GET /health``) needs a Docker
engine; the blocker is recorded in the pull-request description.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "docker-compose.yml"
SCHEMA_PATH = Path(__file__).parent / "data" / "compose-spec.json"
ENV_EXAMPLE_PATH = ROOT / ".env.example"
NGINX_CONF_PATH = ROOT / "infrastructure" / "docker" / "frontend.nginx.conf"
DEPLOYMENT_DOC_PATH = ROOT / "docs" / "DEPLOYMENT.md"

REQUIRED_SERVICES = ("backend", "frontend", "browser-bridge")
DOCKERFILE_PATHS = {
    "backend": "infrastructure/docker/Dockerfile.backend",
    "frontend": "infrastructure/docker/Dockerfile.frontend",
    "browser-bridge": "infrastructure/docker/Dockerfile.bridge",
}
SECRET_VARS = ("NEXUS_JWT_SECRET", "NEXUS_ENCRYPTION_KEY", "NEXUS_BRIDGE_API_TOKEN")

_VAR_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)")
_VAR_SUBSTITUTION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _env_example_values() -> dict[str, str]:
    """Parse active ``KEY=VALUE`` assignments from .env.example (comments skipped)."""
    values: dict[str, str] = {}
    for line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def _interpolate(text: str, values: dict[str, str]) -> str:
    """Substitute ``${VAR}`` / ``${VAR:-default}`` the way Compose does.

    For ``:-`` an empty value counts as unset, matching Compose semantics.
    """

    def substitute(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        current = values.get(name, "")
        if current:
            return current
        if default is not None:
            return default
        return current

    return _VAR_SUBSTITUTION.sub(substitute, text)


def _interpolate_tree(node: object, values: dict[str, str]) -> object:
    """Recursively interpolate every string in a parsed YAML structure."""
    if isinstance(node, str):
        return _interpolate(node, values)
    if isinstance(node, list):
        return [_interpolate_tree(item, values) for item in node]
    if isinstance(node, dict):
        return {key: _interpolate_tree(val, values) for key, val in node.items()}
    return node


def _compose() -> dict[str, object]:
    """docker-compose.yml parsed with .env.example values interpolated in."""
    raw = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict), "docker-compose.yml must be a mapping"
    interpolated = _interpolate_tree(raw, _env_example_values())
    assert isinstance(interpolated, dict)
    return interpolated


def _services() -> dict[str, dict[str, object]]:
    services = _compose()["services"]
    assert isinstance(services, dict)
    return services  # type: ignore[return-value]


def test_compose_file_parses_as_yaml() -> None:
    raw = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    assert isinstance(raw.get("services"), dict), "services must be a mapping"


def test_compose_matches_compose_spec_schema() -> None:
    """Validate the interpolated compose file against the official schema."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=_compose(), schema=schema)


def test_required_services_present() -> None:
    services = _services()
    for name in REQUIRED_SERVICES:
        assert name in services, f"missing service {name!r}"


def test_compose_builds_dockerfiles_at_contracted_paths() -> None:
    services = _services()
    for name, rel_path in DOCKERFILE_PATHS.items():
        build = services[name]["build"]
        assert build["context"] == ".", f"{name}: build context must be repo root"
        assert build["dockerfile"] == rel_path, f"{name}: wrong dockerfile path"
        assert (ROOT / rel_path).is_file(), f"{rel_path} does not exist"


def test_dockerfiles_pin_base_images() -> None:
    for rel_path in DOCKERFILE_PATHS.values():
        lines = (ROOT / rel_path).read_text(encoding="utf-8").splitlines()
        from_lines = [line for line in lines if line.startswith("FROM ")]
        assert from_lines, f"{rel_path}: no FROM instruction"
        for line in from_lines:
            image = line.split()[1]
            assert ":" in image, f"{rel_path}: unpinned image {image!r}"
            assert not image.endswith(":latest"), f"{rel_path}: :latest is forbidden"


def test_backend_dockerfile_contract() -> None:
    text = (ROOT / DOCKERFILE_PATHS["backend"]).read_text(encoding="utf-8")
    assert "EXPOSE 8000" in text
    assert "PYTHONPATH=/app" in text
    assert "alembic -c backend/alembic.ini upgrade head" in text
    assert "uvicorn backend.app.main:app" in text
    assert "USER nexus" in text, "backend must run as a non-root user"


def test_frontend_dockerfile_contract() -> None:
    text = (ROOT / DOCKERFILE_PATHS["frontend"]).read_text(encoding="utf-8")
    assert "FROM node:20-alpine" in text
    assert "FROM nginx:1.27-alpine" in text
    assert "npm run build" in text, "frontend slice must provide a build script"
    assert "COPY infrastructure/docker/frontend.nginx.conf" in text
    assert "EXPOSE 3000" in text


def test_bridge_dockerfile_contract() -> None:
    text = (ROOT / DOCKERFILE_PATHS["browser-bridge"]).read_text(encoding="utf-8")
    assert "EXPOSE 8790" in text
    assert "COPY integrations/browser-bridge/src/" in text
    assert 'CMD ["python", "app.py"]' in text
    assert "USER nexus-bridge" in text, "bridge must run as a non-root user"


def test_bridge_uses_host_network_without_published_ports() -> None:
    """SPEC §3.2: the bridge binds loopback only — host network, no ports."""
    bridge = _services()["browser-bridge"]
    assert bridge.get("network_mode") == "host"
    assert "ports" not in bridge, "host networking forbids published ports"


def test_published_ports_bind_loopback_only() -> None:
    services = _services()
    for name in ("backend", "frontend"):
        ports = services[name]["ports"]
        assert isinstance(ports, list)
        for mapping in ports:
            assert isinstance(mapping, str)
            assert mapping.startswith("127.0.0.1:"), (
                f"{name}: {mapping!r} must bind 127.0.0.1 only (local-first)"
            )


def test_frontend_waits_for_backend_health() -> None:
    depends_on = _services()["frontend"]["depends_on"]
    assert depends_on == {"backend": {"condition": "service_healthy"}}


def test_healthchecks_probe_service_endpoints() -> None:
    services = _services()
    backend_check = " ".join(services["backend"]["healthcheck"]["test"])
    assert "/health" in backend_check and ":8000" in backend_check
    bridge_check = " ".join(services["browser-bridge"]["healthcheck"]["test"])
    assert "/health" in bridge_check and ":8790" in bridge_check
    frontend_check = " ".join(services["frontend"]["healthcheck"]["test"])
    assert ":3000" in frontend_check, "frontend healthcheck must hit its own port"


def test_backend_database_pinned_to_named_volume() -> None:
    compose = _compose()
    backend = compose["services"]["backend"]
    assert "backend-data:/data" in backend["volumes"]
    assert "backend-data" in compose["volumes"], "volume must be declared top-level"
    assert backend["environment"]["NEXUS_DATABASE_URL"] == ("sqlite+aiosqlite:////data/nexus.db"), (
        "compose must pin the container DB path onto the named volume"
    )


def test_every_compose_variable_is_documented_in_env_example() -> None:
    compose_lines = COMPOSE_PATH.read_text(encoding="utf-8").splitlines()
    # Drop YAML comments (full-line and inline: ` #` never occurs inside our values)
    # so prose like "Every ${VAR} below..." doesn't count as a real reference.
    active_yaml = "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in compose_lines)
    referenced = set(_VAR_REFERENCE.findall(active_yaml))
    documented = set(_env_example_values())
    missing = referenced - documented
    assert not missing, f"docker-compose.yml uses vars missing from .env.example: {sorted(missing)}"


def test_env_example_secrets_are_empty() -> None:
    values = _env_example_values()
    for key in SECRET_VARS:
        assert key in values, f"{key} missing from .env.example"
        assert values[key] == "", f"{key} must be empty in .env.example (a value is set)"


def test_dotenv_is_not_tracked_by_git() -> None:
    """A real .env must never be committed (SPEC §11 secret handling)."""
    git = shutil.which("git")
    assert git is not None, "git executable not found on PATH"
    # git is resolved via shutil.which; arguments are fixed literals (S603 false positive).
    result = subprocess.run(  # noqa: S603
        [git, "ls-files", "--", ".env"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"git ls-files failed: {result.stderr.strip()}"
    assert result.stdout.strip() == "", ".env is tracked by git and must not be"


def test_dockerignore_excludes_secrets_and_junk() -> None:
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    entries = {line.strip() for line in lines if line.strip() and not line.strip().startswith("#")}
    assert ".env" in entries, ".env must never enter a build context"
    assert "node_modules" in entries


def test_nginx_proxies_api_and_websocket() -> None:
    conf = NGINX_CONF_PATH.read_text(encoding="utf-8")
    assert "location /api/" in conf
    assert "location /ws/" in conf
    assert "proxy_pass" in conf
    assert "proxy_set_header Upgrade" in conf, "websocket upgrade headers required"
    assert "try_files" in conf, "SPA fallback required"


def test_deployment_doc_documents_stack_startup() -> None:
    doc = DEPLOYMENT_DOC_PATH.read_text(encoding="utf-8")
    assert "docker compose up" in doc, "DEPLOYMENT.md must document the quick start"
    assert "/health" in doc, "DEPLOYMENT.md must document the health endpoint"
