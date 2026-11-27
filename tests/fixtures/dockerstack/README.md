# Container smoke test fixtures

The container images build the real application slices (backend, web and
browser bridge).  While those slices are not merged into `main` yet, there is
nothing to build, so the container smoke test in
`.github/workflows/docker-stack.yml` installs the minimal stand-ins in this
directory.

| Fixture | Installed as | Provides |
|---|---|---|
| `backend/` | `backend/` | FastAPI application with the public `GET /health` endpoint |
| `frontend/` | `apps/web/` | `npm run build` that writes a static `dist/` bundle |
| `bridge/` | `integrations/browser-bridge/` | FastAPI application with `GET /health`, the same factory API as the real bridge |

The fixtures are installed by `install_fixtures.py`, which never overwrites a
real slice: a slice that is present is kept and the fixture is skipped.  As
soon as the backend, web and bridge slices are merged, the smoke test runs
against the real applications.

The fixtures are test data.  They are not part of the product and must never
be imported by the application itself.
