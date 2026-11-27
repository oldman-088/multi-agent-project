# Implementation status

Status of the features of this repository. `Complete` means implemented and
covered by a test that passes; `Partial` means implemented with a documented
gap; `Not started` means not built; `Blocked` means it cannot be built in the
current environment.

## Runtime environment and containers (AATM-d899439f)

| Feature | Status | Implementation path | Tests | Notes |
|---|---|---|---|---|
| Local stack definition (`backend`, `frontend`, `browser-bridge`) | Complete | `docker-compose.yml` | `tests/test_docker_stack.py::test_compose_file_contains_the_three_services` | Validated against the official Compose Specification schema |
| Backend image | Complete | `infrastructure/docker/Dockerfile.backend` | `tests/test_docker_stack.py::test_backend_dockerfile_applies_migrations_and_serves_with_uvicorn` | Runs the migrations, then serves on `0.0.0.0:8000` as an unprivileged user |
| Frontend image | Complete | `infrastructure/docker/Dockerfile.frontend` | `tests/test_docker_stack.py::test_frontend_dockerfile_builds_the_bundle_and_serves_it_with_nginx` | Node build stage, nginx runtime stage, unprivileged |
| Browser bridge image | Complete | `infrastructure/docker/Dockerfile.bridge` | `tests/test_docker_stack.py::test_bridge_dockerfile_starts_the_bridge_entry_point` | Keeps the bridge's own pairing, origin and token checks |
| API and WebSocket proxy | Complete | `infrastructure/docker/frontend.nginx.conf` | `tests/test_docker_stack.py::test_nginx_proxies_the_api_and_the_websocket_to_the_backend_service` | Relative URLs only, upstream is the compose service name |
| Health endpoints | Complete | `docker-compose.yml`, the three Dockerfiles | `tests/test_docker_stack.py::test_backend_healthcheck_calls_the_health_endpoint` | `/health` on backend and bridge, `/healthz` on the frontend |
| Environment template | Complete | `.env.example` | `tests/test_docker_stack.py::test_env_example_documents_every_variable_used_by_the_compose_file` | Every variable documented, every secret empty |
| Loopback-only exposure | Complete | `docker-compose.yml` | `tests/test_docker_stack.py::test_every_published_port_is_bound_to_the_loopback_interface` | Every published port is bound to `127.0.0.1` |
| Layout-independent image builds | Complete | `infrastructure/docker/resolve_source.py` | `tests/test_docker_stack.py::test_resolver_*` | Supports `backend/` and `apps/backend/`, `apps/web/` and `integrations/browser-bridge/` |
| Container smoke test | Complete | `.github/workflows/docker-stack.yml` | the workflow itself | Two jobs: a deterministic build from the fixtures (blocking) and the same smoke test with the merged application slices (informational) |
| Local documentation | Complete | `docs/DEPLOYMENT.md` | — | Quick start, variables, security notes, design decisions, troubleshooting |
| Building and starting the images in the development environment of this session | Blocked | — | — | Docker is not installed in that environment; the container pipeline is verified by the workflow instead |

## Other slices

The backend, the web application, the browser bridge and the userscript are
built by the other slices of this project; see the pull requests of the
project for their status.
