# Development log

One entry per session. Newest first.

## 2026-11-27 — Worker 6, runtime environment and containers (AATM-d899439f)

### Environment

| | |
|---|---|
| OS | Debian 12 (bookworm), Linux 5.6 / x86_64 |
| Python | 3.11.2 (the images use Python 3.12) |
| Node | v22.22.3, npm 10.9.8 |
| Docker | **not available** in this environment (`docker: command not found`, no `/var/run/docker.sock`, no podman) |
| Network | available (GitHub, PyPI) |

### Work done

* `docker-compose.yml` with the three services `backend`, `frontend` and
  `browser-bridge`, health checks, a named volume for the database and
  loopback-only published ports.
* `infrastructure/docker/Dockerfile.backend`, `Dockerfile.frontend` and
  `Dockerfile.bridge`, plus `frontend.nginx.conf`, `bridge_entrypoint.py` and
  the build-time source resolver `resolve_source.py`.
* `.env.example` with every variable the stack reads; all secrets are empty.
* `.dockerignore` so no `.env`, cache or database ends up in an image.
* `docs/DEPLOYMENT.md`: how to start the stack locally, the variables, the
  security posture, the design decisions and the troubleshooting table.
* `tests/test_docker_stack.py`: 41 tests covering the compose file, the
  images, the environment template and the resolver.
* `tests/fixtures/dockerstack/`: minimal stand-ins used by the container smoke
  test while the application slices are not merged yet.
* `.github/workflows/docker-stack.yml`: validates the compose file, runs the
  static tests, builds the three images, starts the stack and checks the
  health endpoints.

### Decisions

* **The application directory is resolved at build time.** The backend package
  exists both as `backend/` and as `apps/backend/`, and the web application
  can live in `apps/web/` or in a repository root `package.json`. Hard-coding
  one path would break the images as soon as the other slice is merged, so
  every image asks `resolve_source.py` where the code is. Only the
  dependencies are installed, never the package itself, which keeps the image
  independent from the packaging metadata of a slice.
* **The bridge shares the network namespace of the backend**
  (`network_mode: service:backend`). The backend then reaches the bridge on
  `127.0.0.1`, which keeps its own loopback-only validation valid, and the
  userscript reaches the same bridge through the published port.
* **The bridge listens on `0.0.0.0` inside its own namespace.** A process
  bound to the loopback address of a container is unreachable from the host,
  so the published port would never answer. The published port stays bound to
  `127.0.0.1` on the host, so the bridge is still not reachable from the
  network of the machine. `NEXUS_BRIDGE_BIND_HOST=127.0.0.1` restores the
  strict bind and disables the published port.
* **The frontend is served by the unprivileged nginx image** so no service in
  the stack runs as root.

### Reused code

None copied. The images reuse the application slices as they are; the only
new code is the resolver, the bridge entry point and the nginx configuration.

### New dependencies

None at runtime. The test suite uses `pytest`, `PyYAML` and `jsonschema`,
which are installed by the workflow; the two optional ones are guarded with
`pytest.importorskip`, so the suite still runs without them.

### Tests run

| Command | Result |
|---|---|
| `python -m pytest tests/test_docker_stack.py -q` (Python 3.11, pytest 9.2, PyYAML 6.0.4, jsonschema 4.x) | **41 passed** |
| `python infrastructure/docker/resolve_source.py --root . --env-file ... backend\|frontend\|bridge` against the fixtures | resolved `backend.app.main:app`, `apps/web`, `integrations/browser-bridge/src` |
| `python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000` (the command of the image) and `curl http://127.0.0.1:8000/health` | **HTTP 200** `{"status":"ok",...}` |
| `python infrastructure/docker/bridge_entrypoint.py` (the command of the image) and `curl http://127.0.0.1:8790/health` | **HTTP 200** `{"status":"ok",...}` |
| `node build.mjs` (the build of the frontend image) | wrote `dist/index.html` |
| `docker compose config --quiet` | **not run here** — Docker is unavailable in this environment; it runs in the workflow |

### Known issues

* Docker is not installed in the development environment of this session, so
  the three images were not built and the stack was not started with Docker
  here. The container pipeline is verified by
  `.github/workflows/docker-stack.yml` on a runner with Docker; the commands
  the images run were verified natively, as listed above.
* The compose file, the images and the resolver do not depend on the
  application slices, but the images need them at build time. Until the
  backend, web and bridge slices are merged, the smoke test falls back to the
  fixtures in `tests/fixtures/dockerstack/`.

### Next step

Merge the backend, web and bridge slices and re-run the container smoke test
against the real applications.
