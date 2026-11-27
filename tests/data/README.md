# Test data

## `compose-spec.json`

The official JSON Schema of the [Compose Specification][spec], vendored so
that `tests/test_docker_stack.py` can validate `docker-compose.yml` without a
Docker installation and without network access.

| | |
|---|---|
| Source | <https://github.com/compose-spec/compose-spec/blob/main/schema/compose-spec.json> |
| Upstream commit | `6b3a2a93e77c30ded1aa8264307e74d1208a6eae` (2026-11-17) |
| License | Apache-2.0 |

Refresh it with:

```bash
gh api repos/compose-spec/compose-spec/contents/schema/compose-spec.json \
  --jq '.content' | base64 -d > tests/data/compose-spec.json
```

[spec]: https://github.com/compose-spec/compose-spec
