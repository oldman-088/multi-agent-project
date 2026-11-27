#!/usr/bin/env python3
"""Locate the application sources that the NEXUS container images build.

The repository is assembled from several slices that land independently, and
the backend package exists in more than one plausible location:

* ``backend/``       -- the package sits at the repository root
* ``apps/backend/``  -- the layout described in ``docs/SPEC.md`` section 10

Hard-coding one of them in a Dockerfile would break the image as soon as the
other slice is merged.  Instead every image copies the repository once and
asks this script where the code actually is.  The answer is written to a
small ``KEY=VALUE`` file that the Dockerfiles ``.``-source before they build.

Usage::

    resolve_source.py --root /src --env-file /tmp/build.env \
                      --requirements-file /tmp/requirements.txt backend

``backend``, ``frontend`` and ``bridge`` are the supported roles.  The script
exits non-zero with an actionable message when a role cannot be resolved, so
a broken build fails loudly instead of producing an empty image.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROLES = ("backend", "frontend", "bridge")

# Candidate source directories per role, most specific first.
BACKEND_CANDIDATES = ("apps/backend", "backend", "src/backend")
FRONTEND_CANDIDATES = ("apps/web", "web", "frontend", ".")
BRIDGE_CANDIDATES = ("integrations/browser-bridge", "browser-bridge", "bridge")

# Dependency sets used when a slice ships no manifest of its own.  They cover
# the imports of the smallest possible service (FastAPI + uvicorn) so a fixture
# build still works.
FALLBACK_REQUIREMENTS = (
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "pydantic>=2.6",
)


class ResolutionError(RuntimeError):
    """Raised when a role cannot be resolved inside the given root."""


@dataclass
class Resolution:
    """The facts a Dockerfile needs about one role."""

    values: dict[str, str] = field(default_factory=dict)
    requirements: list[str] = field(default_factory=list)

    def as_env(self) -> str:
        return "".join(f"{key}={value}\n" for key, value in sorted(self.values.items()))


# --------------------------------------------------------------------------- helpers
def _read_package_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _pyproject_requirements(path: Path) -> list[str]:
    """Return the runtime dependencies declared by a ``pyproject.toml``."""

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    project = data.get("project")
    if not isinstance(project, dict):
        return []
    deps = project.get("dependencies")
    if not isinstance(deps, list):
        return []
    return [str(dep) for dep in deps if isinstance(dep, str) and dep.strip()]


def _manifest(base: Path, names: tuple[str, ...]) -> tuple[Path | None, list[str]]:
    """Find the first manifest of ``names`` in ``base`` or its parents.

    Returns the manifest path (or ``None``) and the requirements it declares.
    A ``requirements.txt`` is used verbatim; a ``pyproject.toml`` contributes
    its ``project.dependencies`` list.  The project itself is never installed
    -- only its dependencies -- so the image never depends on the packaging
    metadata of a particular slice.
    """

    for directory in (base, *base.parents):
        for name in names:
            manifest = directory / name
            if not manifest.is_file():
                continue
            if name == "requirements.txt":
                lines = [
                    line.strip()
                    for line in manifest.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.strip().startswith("#")
                ]
                return manifest, lines
            requirements = _pyproject_requirements(manifest)
            if requirements:
                return manifest, requirements
    return None, []


# --------------------------------------------------------------------------- roles
def resolve_backend(root: Path) -> Resolution:
    """Resolve the backend package, its import root and its dependencies."""

    package_dir: Path | None = None
    for relative in BACKEND_CANDIDATES:
        candidate = root / relative
        if (candidate / "app" / "main.py").is_file():
            package_dir = candidate
            break
    if package_dir is None:
        searched = ", ".join(BACKEND_CANDIDATES)
        raise ResolutionError(
            "no backend application found in "
            f"{root} (looked for app/main.py in: {searched}). "
            "Merge the backend slice or point the image at the right directory."
        )

    import_root = package_dir.parent
    package_name = package_dir.name
    module = f"{package_name}.app.main:app"

    manifest, requirements = _manifest(package_dir, ("requirements.txt", "pyproject.toml"))
    alembic_ini = package_dir / "alembic.ini"
    if not alembic_ini.is_file():
        alembic_ini = import_root / "alembic.ini"

    resolution = Resolution(
        values={
            "NEXUS_BACKEND_SRC": str(package_dir),
            "NEXUS_BACKEND_PACKAGE": package_name,
            "NEXUS_BACKEND_IMPORT_ROOT": str(import_root),
            "NEXUS_BACKEND_MODULE": module,
            "NEXUS_BACKEND_MANIFEST": str(manifest) if manifest else "",
            "NEXUS_BACKEND_ALEMBIC": str(alembic_ini) if alembic_ini.is_file() else "",
        },
        requirements=requirements,
    )
    return resolution


def resolve_frontend(root: Path) -> Resolution:
    """Resolve the web application directory and its build output."""

    source_dir: Path | None = None
    for relative in FRONTEND_CANDIDATES:
        candidate = root / relative
        package_json = candidate / "package.json"
        if not package_json.is_file():
            continue
        scripts = _read_package_json(package_json).get("scripts")
        if isinstance(scripts, dict) and "build" in scripts:
            source_dir = candidate
            break
    if source_dir is None:
        searched = ", ".join(FRONTEND_CANDIDATES)
        raise ResolutionError(
            "no frontend application found in "
            f"{root} (looked for a package.json with a 'build' script in: {searched}). "
            "Merge the web slice or point the image at the right directory."
        )

    lockfile = source_dir / "package-lock.json"
    resolution = Resolution(
        values={
            "NEXUS_FRONTEND_SRC": str(source_dir),
            "NEXUS_FRONTEND_PACKAGE": str(source_dir / "package.json"),
            "NEXUS_FRONTEND_LOCKFILE": str(lockfile) if lockfile.is_file() else "",
            "NEXUS_FRONTEND_DIST": str(source_dir / "dist"),
        },
        requirements=[],
    )
    return resolution


def resolve_bridge(root: Path) -> Resolution:
    """Resolve the Local Browser Bridge application directory."""

    app_dir: Path | None = None
    source_dir: Path | None = None
    for relative in BRIDGE_CANDIDATES:
        candidate = root / relative
        nested = candidate / "src" / "app.py"
        if nested.is_file():
            app_dir = nested.parent
            source_dir = candidate
            break
        flat = candidate / "app.py"
        if flat.is_file():
            app_dir = candidate
            source_dir = candidate
            break
    if app_dir is None or source_dir is None:
        searched = ", ".join(BRIDGE_CANDIDATES)
        raise ResolutionError(
            "no browser bridge application found in "
            f"{root} (looked for src/app.py in: {searched}). "
            "Merge the bridge slice or point the image at the right directory."
        )

    manifest, requirements = _manifest(source_dir, ("requirements.txt", "pyproject.toml"))
    resolution = Resolution(
        values={
            "NEXUS_BRIDGE_SRC": str(source_dir),
            "NEXUS_BRIDGE_APP_DIR": str(app_dir),
            "NEXUS_BRIDGE_MANIFEST": str(manifest) if manifest else "",
        },
        requirements=requirements,
    )
    return resolution


RESOLVERS = {
    "backend": resolve_backend,
    "frontend": resolve_frontend,
    "bridge": resolve_bridge,
}


# --------------------------------------------------------------------------- cli
def resolve(role: str, root: Path) -> Resolution:
    """Resolve ``role`` inside ``root``."""

    try:
        resolver = RESOLVERS[role]
    except KeyError:
        raise ResolutionError(f"unknown role {role!r}; expected one of {', '.join(ROLES)}") from None
    return resolver(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("role", choices=ROLES, help="which application to resolve")
    parser.add_argument("--root", default=".", help="repository root (default: current directory)")
    parser.add_argument("--env-file", help="write the resolved KEY=VALUE pairs to this file")
    parser.add_argument(
        "--requirements-file",
        help="write the resolved dependency list to this file",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    try:
        resolution = resolve(args.role, root)
    except ResolutionError as exc:
        print(f"resolve_source.py: {exc}", file=sys.stderr)
        return 1

    env_text = resolution.as_env()
    if args.env_file:
        env_path = Path(args.env_file)
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(env_text, encoding="utf-8")
    else:
        sys.stdout.write(env_text)

    requirements = resolution.requirements or list(FALLBACK_REQUIREMENTS)
    if args.requirements_file:
        requirements_path = Path(args.requirements_file)
        requirements_path.parent.mkdir(parents=True, exist_ok=True)
        requirements_path.write_text(
            "".join(f"{item}\n" for item in requirements), encoding="utf-8"
        )
    else:
        sys.stdout.write("".join(f"{item}\n" for item in requirements))

    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
