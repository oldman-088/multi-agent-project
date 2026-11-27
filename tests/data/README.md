# Test data

- `compose-spec.json` — the official **Compose Specification** JSON schema
  (draft 2020-12), vendored so `tests/test_docker_stack.py` can validate
  `docker-compose.yml` offline and deterministically.

  Source: <https://github.com/compose-spec/compose-spec>  
  License: Apache-2.0 (© Compose Specification contributors) — this copy is
  unmodified; see the upstream repository for the full license text.

  It is data, not executable code: pytest only reads it.
