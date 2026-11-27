"""Static validation of the NEXUS container stack.

The tests in this module check the artefacts of the runtime environment:
`docker-compose.yml`, the three service images under `infrastructure/docker/`,
the environment template and the build-time source resolver.

They are deliberately dependency-light: PyYAML and jsonschema are optional and
the tests that need them are skipped when they are not installed
(AGENTS.md: a test that needs a package only some jobs install must guard the
import).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

try:  # pragma: no cover - optional dependency
    import yaml
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    yaml = None

try:  # pragma: no cover - optional dependency
    import jsonschema
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    jsonschema = None

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
DOCKER_DIR = REPO_ROOT / "infrastructure" / "docker"
BACKEND_DOCKERFILE = DOCKER_DIR / "Dockerfile.backend"
FRONTEND_DOCKERFILE = DOCKER_DIR / "Dockerfile.frontend"
BRIDGE_DOCKERFILE = DOCKER_DIR / "Dockerfile.bridge"
NGINX_CONF = DOCKER_DIR / "frontend.nginx.conf"
COMPOSE_SCHEMA = REPO_ROOT / "tests" / "data" / "compose-spec.json"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "dockerstack"

requires_yaml = pytest.mark.skipif(yaml is None, reason="PyYAML is not installed")
requires_jsonschema = pytest.mark.skipif(
    jsonschema is None, reason="jsonschema is not installed"
)

SERVICES = ("backend", "frontend", "browser-bridge")

# Variables that hold a secret and therefore have to stay empty in the
# template.  The values are names, never the secrets themselves.
SECRET_VARIABLES = (
    "NEXUS_JWT_SECRET",
    "NEXUS_ENCRYPTION_KEY",
    "NEXUS_BRIDGE_API_TOKEN",
    "NEXUS_OPENAI_API_KEY_REF",
)

# The backend settings of docs/SPEC.md section 4 and the backend slice.  Every
# one of them has to be documented in the environment template.
BACKEND_SETTINGS = (
    "NEXUS_ENV",
    "NEXUS_LOG_LEVEL",
    "NEXUS_DATABASE_URL",
    "NEXUS_DB_ECHO",
    "NEXUS_JWT_SECRET",
    "NEXUS_JWT_ALGORITHM",
    "NEXUS_ACCESS_TOKEN_TTL_SECONDS",
    "NEXUS_REFRESH_TOKEN_TTL_SECONDS",
    "NEXUS_MAX_FAILED_LOGINS",
    "NEXUS_LOCKOUT_SECONDS",
    "NEXUS_ENCRYPTION_KEY",
    "NEXUS_BRIDGE_HOST",
    "NEXUS_BRIDGE_PORT",
    "NEXUS_BRIDGE_ALLOWED_ORIGINS",
    "NEXUS_OPENAI_ENABLED",
    "NEXUS_OPENAI_BASE_URL",
    "NEXUS_OPENAI_API_KEY_REF",
    "NEXUS_OLLAMA_BASE_URL",
)


# --------------------------------------------------------------------------- helpers
def load_compose() -> dict:
    """Parse the compose file."""

    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


def env_pairs(text: str) -> dict[str, str]:
    """Parse the `KEY=value` lines of an environment file."""

    pairs: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        pairs[key.strip()] = value.strip()
    return pairs


def compose_variables(text: str) -> set[str]:
    """Return every `${VAR}` / `${VAR:-default}` referenced by the compose file."""

    return set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)", text))


def dockerfile_instructions(text: str) -> list[tuple[str, str]]:
    """Return the (instruction, argument) pairs of a Dockerfile."""

    instructions: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        instructions.append((parts[0].upper(), parts[1] if len(parts) > 1 else ""))
    return instructions


def load_resolver():
    """Import `infrastructure/docker/resolve_source.py` as a module."""

    path = DOCKER_DIR / "resolve_source.py"
    spec = importlib.util.spec_from_file_location("nexus_resolve_source", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # The module has to be registered before it is executed: dataclasses
    # resolve the annotations of the dataclass through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_installer():
    """Import `tests/fixtures/dockerstack/install_fixtures.py` as a module."""

    path = FIXTURE_DIR / "install_fixtures.py"
    spec = importlib.util.spec_from_file_location("nexus_install_fixtures", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- compose file
@requires_yaml
def test_compose_file_contains_the_three_services() -> None:
    compose = load_compose()
    assert "services" in compose
    for service in SERVICES:
        assert service in compose["services"], f"missing service {service}"


@requires_yaml
def test_compose_file_has_no_obsolete_version_key() -> None:
    compose = load_compose()
    assert "version" not in compose, "the Compose Specification dropped the version key"


@requires_yaml
@requires_jsonschema
def test_compose_file_validates_against_the_compose_specification() -> None:
    schema = json.loads(COMPOSE_SCHEMA.read_text(encoding="utf-8"))
    compose = load_compose()
    jsonschema.validate(instance=compose, schema=schema)


@requires_yaml
def test_every_published_port_is_bound_to_the_loopback_interface() -> None:
    compose = load_compose()
    published = [
        mapping
        for service in compose["services"].values()
        for mapping in service.get("ports", [])
    ]
    assert published, "the stack publishes no ports at all"
    for mapping in published:
        assert mapping.startswith("127.0.0.1:"), (
            f"{mapping!r} is published on every interface; the local stack must stay "
            "reachable from this machine only"
        )


@requires_yaml
def test_every_service_has_a_healthcheck() -> None:
    compose = load_compose()
    for name, service in compose["services"].items():
        assert "healthcheck" in service, f"service {name} has no healthcheck"
        assert service["healthcheck"].get("test"), f"service {name} has an empty healthcheck"


@requires_yaml
def test_backend_healthcheck_calls_the_health_endpoint() -> None:
    compose = load_compose()
    backend = compose["services"]["backend"]
    test = " ".join(backend["healthcheck"]["test"])
    assert "/health" in test


@requires_yaml
def test_services_are_built_from_the_infrastructure_dockerfiles() -> None:
    compose = load_compose()
    expected = {
        "backend": "infrastructure/docker/Dockerfile.backend",
        "frontend": "infrastructure/docker/Dockerfile.frontend",
        "browser-bridge": "infrastructure/docker/Dockerfile.bridge",
    }
    for service, dockerfile in expected.items():
        build = compose["services"][service].get("build")
        assert build, f"service {service} is not built from an image"
        assert build["dockerfile"] == dockerfile
        assert (REPO_ROOT / dockerfile).is_file(), f"missing {dockerfile}"


@requires_yaml
def test_bridge_shares_the_network_namespace_of_the_backend() -> None:
    compose = load_compose()
    bridge = compose["services"]["browser-bridge"]
    assert bridge.get("network_mode") == "service:backend", (
        "the bridge has to share the network namespace of the backend so the backend "
        "can reach it on 127.0.0.1"
    )
    # A service that shares another namespace cannot publish ports itself.
    assert "ports" not in bridge


@requires_yaml
def test_bridge_port_is_published_by_the_backend_service() -> None:
    compose = load_compose()
    backend_ports = compose["services"]["backend"]["ports"]
    assert any("NEXUS_BRIDGE_PORT" in mapping for mapping in backend_ports), (
        "the bridge port has to be published by the backend service, which owns the "
        "shared network namespace"
    )


@requires_yaml
def test_backend_reaches_the_bridge_on_the_loopback_address() -> None:
    compose = load_compose()
    environment = compose["services"]["backend"]["environment"]
    assert environment["NEXUS_BRIDGE_HOST"] == "127.0.0.1"


@requires_yaml
def test_frontend_depends_on_a_healthy_backend() -> None:
    compose = load_compose()
    depends_on = compose["services"]["frontend"]["depends_on"]
    assert depends_on["backend"]["condition"] == "service_healthy"


@requires_yaml
def test_backend_uses_a_named_volume_for_the_database() -> None:
    compose = load_compose()
    volumes = compose["services"]["backend"]["volumes"]
    assert any("backend-data" in mapping for mapping in volumes)
    assert "backend-data" in compose["volumes"]


# --------------------------------------------------------------------------- environment template
def test_env_example_documents_every_variable_used_by_the_compose_file() -> None:
    variables = compose_variables(COMPOSE_FILE.read_text(encoding="utf-8"))
    documented = env_pairs(ENV_EXAMPLE.read_text(encoding="utf-8"))
    missing = sorted(variables - set(documented))
    assert not missing, f"variables used by docker-compose.yml but not documented: {missing}"


def test_env_example_documents_every_backend_setting() -> None:
    documented = env_pairs(ENV_EXAMPLE.read_text(encoding="utf-8"))
    missing = sorted(set(BACKEND_SETTINGS) - set(documented))
    assert not missing, f"backend settings missing from .env.example: {missing}"


def test_env_example_contains_no_real_secrets() -> None:
    documented = env_pairs(ENV_EXAMPLE.read_text(encoding="utf-8"))
    for name in SECRET_VARIABLES:
        assert name in documented, f"{name} is not documented"
        assert documented[name] == "", f"{name} must stay empty in the template"


def test_env_example_contains_no_credential_looking_values() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for pattern in (r"sk-[A-Za-z0-9]{16,}", r"ghp_[A-Za-z0-9]{20,}", r"AKIA[0-9A-Z]{16}"):
        assert re.search(pattern, text) is None, f"the template looks like it contains a key ({pattern})"


def test_env_example_documents_how_to_generate_the_secrets() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "secrets.token_urlsafe" in text
    assert "Fernet.generate_key" in text


def test_dockerignore_excludes_env_files_but_keeps_the_template() -> None:
    lines = {
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert ".env" in lines
    assert "!.env.example" in lines


# --------------------------------------------------------------------------- Dockerfiles
@pytest.mark.parametrize(
    "dockerfile",
    [BACKEND_DOCKERFILE, FRONTEND_DOCKERFILE, BRIDGE_DOCKERFILE],
    ids=["backend", "frontend", "bridge"],
)
def test_dockerfiles_run_as_a_non_root_user(dockerfile: Path) -> None:
    users = [
        argument.strip()
        for instruction, argument in dockerfile_instructions(dockerfile.read_text(encoding="utf-8"))
        if instruction == "USER"
    ]
    assert users, f"{dockerfile.name} never switches user"
    assert users[-1] not in {"root", "0"}, f"{dockerfile.name} runs as root"


@pytest.mark.parametrize(
    "dockerfile",
    [BACKEND_DOCKERFILE, FRONTEND_DOCKERFILE, BRIDGE_DOCKERFILE],
    ids=["backend", "frontend", "bridge"],
)
def test_dockerfiles_do_not_bake_secrets_into_the_image(dockerfile: Path) -> None:
    instructions = dockerfile_instructions(dockerfile.read_text(encoding="utf-8"))
    for instruction, argument in instructions:
        if instruction not in {"ENV", "ARG"}:
            continue
        for assignment in argument.split():
            name, separator, value = assignment.partition("=")
            if not separator:
                continue
            if re.search(r"SECRET|PASSWORD|TOKEN|KEY", name):
                assert value == "", (
                    f"{dockerfile.name} gives {name} a default value through {instruction}; "
                    "secrets belong in the environment, not in the image"
                )


def test_backend_dockerfile_applies_migrations_and_serves_with_uvicorn() -> None:
    text = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    assert "alembic" in text and "upgrade head" in text
    assert "uvicorn" in text
    assert "--host 0.0.0.0" in text, "the container has to listen on all its addresses"
    assert "resolve_source.py" in text


def test_frontend_dockerfile_builds_the_bundle_and_serves_it_with_nginx() -> None:
    text = FRONTEND_DOCKERFILE.read_text(encoding="utf-8")
    assert "npm run build" in text
    assert "nginx" in text
    assert "resolve_source.py" in text


def test_bridge_dockerfile_starts_the_bridge_entry_point() -> None:
    text = BRIDGE_DOCKERFILE.read_text(encoding="utf-8")
    assert "bridge_entrypoint.py" in text
    assert "resolve_source.py" in text


def test_bridge_entry_point_keeps_the_loopback_default() -> None:
    text = (DOCKER_DIR / "bridge_entrypoint.py").read_text(encoding="utf-8")
    assert 'DEFAULT_BIND_HOST = "127.0.0.1"' in text
    assert "create_app" in text and "BridgeSettings" in text


# --------------------------------------------------------------------------- nginx
def test_nginx_proxies_the_api_and_the_websocket_to_the_backend_service() -> None:
    text = NGINX_CONF.read_text(encoding="utf-8")
    assert "location /api/" in text
    assert "location /ws" in text
    assert "Upgrade" in text and "Connection" in text
    assert "backend:8000" in text


def test_nginx_never_points_at_localhost() -> None:
    text = NGINX_CONF.read_text(encoding="utf-8")
    # Comments are not configuration.
    uncommented = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )
    assert "localhost" not in uncommented
    assert "127.0.0.1" not in uncommented, "the upstream has to be the compose service name"


# --------------------------------------------------------------------------- resolver
@pytest.fixture()
def resolver():
    return load_resolver()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_resolver_finds_the_backend_at_the_repository_root(resolver, tmp_path: Path) -> None:
    _write(tmp_path / "backend" / "__init__.py", "")
    _write(tmp_path / "backend" / "app" / "__init__.py", "")
    _write(tmp_path / "backend" / "app" / "main.py", "app = object()")

    resolution = resolver.resolve("backend", tmp_path)

    assert resolution.values["NEXUS_BACKEND_SRC"] == str(tmp_path / "backend")
    assert resolution.values["NEXUS_BACKEND_IMPORT_ROOT"] == str(tmp_path)
    assert resolution.values["NEXUS_BACKEND_MODULE"] == "backend.app.main:app"


def test_resolver_finds_the_backend_in_the_apps_layout(resolver, tmp_path: Path) -> None:
    _write(tmp_path / "apps" / "backend" / "__init__.py", "")
    _write(tmp_path / "apps" / "backend" / "app" / "__init__.py", "")
    _write(tmp_path / "apps" / "backend" / "app" / "main.py", "app = object()")

    resolution = resolver.resolve("backend", tmp_path)

    assert resolution.values["NEXUS_BACKEND_SRC"] == str(tmp_path / "apps" / "backend")
    assert resolution.values["NEXUS_BACKEND_IMPORT_ROOT"] == str(tmp_path / "apps")
    assert resolution.values["NEXUS_BACKEND_MODULE"] == "backend.app.main:app"


def test_resolver_reports_a_missing_backend(resolver, tmp_path: Path) -> None:
    with pytest.raises(resolver.ResolutionError) as excinfo:
        resolver.resolve("backend", tmp_path)
    message = str(excinfo.value)
    assert "backend" in message
    assert "apps/backend" in message and "backend" in message


def test_resolver_reads_the_dependencies_of_a_pyproject(resolver, tmp_path: Path) -> None:
    _write(tmp_path / "backend" / "__init__.py", "")
    _write(tmp_path / "backend" / "app" / "main.py", "app = object()")
    _write(
        tmp_path / "pyproject.toml",
        '[project]\nname = "demo"\nversion = "0"\ndependencies = ["fastapi>=0.110"]\n',
    )

    resolution = resolver.resolve("backend", tmp_path)

    assert resolution.requirements == ["fastapi>=0.110"]
    assert resolution.values["NEXUS_BACKEND_MANIFEST"] == str(tmp_path / "pyproject.toml")


def test_resolver_falls_back_to_a_requirements_file(resolver, tmp_path: Path) -> None:
    _write(tmp_path / "backend" / "__init__.py", "")
    _write(tmp_path / "backend" / "app" / "main.py", "app = object()")
    _write(tmp_path / "backend" / "requirements.txt", "# comment\nuvicorn\n")

    resolution = resolver.resolve("backend", tmp_path)

    assert resolution.requirements == ["uvicorn"]


def test_resolver_finds_the_frontend_with_a_build_script(resolver, tmp_path: Path) -> None:
    _write(tmp_path / "package.json", '{"scripts": {"dev": "vite"}}')
    _write(tmp_path / "apps" / "web" / "package.json", '{"scripts": {"build": "vite build"}}')

    resolution = resolver.resolve("frontend", tmp_path)

    assert resolution.values["NEXUS_FRONTEND_SRC"] == str(tmp_path / "apps" / "web")
    assert resolution.values["NEXUS_FRONTEND_DIST"] == str(tmp_path / "apps" / "web" / "dist")


def test_resolver_reports_a_missing_frontend(resolver, tmp_path: Path) -> None:
    with pytest.raises(resolver.ResolutionError):
        resolver.resolve("frontend", tmp_path)


def test_resolver_finds_the_bridge(resolver, tmp_path: Path) -> None:
    _write(tmp_path / "integrations" / "browser-bridge" / "src" / "app.py", "app = object()")

    resolution = resolver.resolve("bridge", tmp_path)

    assert resolution.values["NEXUS_BRIDGE_APP_DIR"] == str(
        tmp_path / "integrations" / "browser-bridge" / "src"
    )


def test_resolver_reports_a_missing_bridge(resolver, tmp_path: Path) -> None:
    with pytest.raises(resolver.ResolutionError):
        resolver.resolve("bridge", tmp_path)


def test_resolver_cli_writes_the_build_facts(resolver, tmp_path: Path) -> None:
    _write(tmp_path / "backend" / "__init__.py", "")
    _write(tmp_path / "backend" / "app" / "main.py", "app = object()")
    env_file = tmp_path / "build.env"
    requirements_file = tmp_path / "requirements.txt"

    exit_code = resolver.main(
        [
            "backend",
            "--root",
            str(tmp_path),
            "--env-file",
            str(env_file),
            "--requirements-file",
            str(requirements_file),
        ]
    )

    assert exit_code == 0
    assert "NEXUS_BACKEND_MODULE=backend.app.main:app" in env_file.read_text(encoding="utf-8")
    assert requirements_file.read_text(encoding="utf-8").strip()


def test_resolver_cli_fails_when_the_role_cannot_be_resolved(resolver, tmp_path: Path) -> None:
    exit_code = resolver.main(["bridge", "--root", str(tmp_path)])

    assert exit_code == 1


# --------------------------------------------------------------------------- fixtures
@pytest.fixture()
def installer():
    return load_installer()


def test_installer_reports_the_missing_slices(installer, tmp_path: Path, capsys) -> None:
    exit_code = installer.main(["--root", str(tmp_path), "--check"])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "backend: missing" in output
    assert "frontend: missing" in output
    assert "bridge: missing" in output


def test_installer_installs_the_missing_slices(installer, tmp_path: Path) -> None:
    installed = installer.install(tmp_path)

    assert installed == 3
    assert (tmp_path / "backend" / "app" / "main.py").is_file()
    assert (tmp_path / "apps" / "web" / "package.json").is_file()
    assert (tmp_path / "integrations" / "browser-bridge" / "src" / "app.py").is_file()


def test_installer_keeps_a_real_slice(installer, tmp_path: Path) -> None:
    _write(tmp_path / "backend" / "app" / "main.py", "app = object()")

    installed = installer.install(tmp_path)

    assert installed == 2
    assert (tmp_path / "backend" / "app" / "main.py").read_text(encoding="utf-8") == "app = object()"


def test_installer_force_replaces_a_real_slice(installer, tmp_path: Path) -> None:
    _write(tmp_path / "backend" / "app" / "main.py", "app = object()")
    _write(tmp_path / "apps" / "backend" / "app" / "main.py", "app = object()")

    installed = installer.install(tmp_path, force=True)

    assert installed == 3
    # The fixture is the only application the resolver can find afterwards.
    assert not (tmp_path / "apps" / "backend").exists()
    assert (tmp_path / "backend" / "app" / "main.py").is_file()
    assert "FastAPI" in (tmp_path / "backend" / "app" / "main.py").read_text(encoding="utf-8")
