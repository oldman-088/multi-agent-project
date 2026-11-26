# Development Log

## Session 1 — 2026-11-26 — Phase 0 (bounded setup research)

**Environment:** Ubuntu 24.04 (Linux 7.0.0-43), Python 3.12.3, Node v22.23.3, npm 10.9.9 (no pnpm), uv installed,
Docker 29.1.3 (usable without sudo), Docker Compose 2.40.3, Chrome and Firefox installed, network available (git, pip, npm all work).

**Work done:**
- The working directory was empty. I initialised a git repository and saved the specification as `docs/SPEC.md`.
- Shallow-cloned the 12 reference repositories plus `OpenHands/software-agent-sdk` into `research/repos/` (git-ignored). SHAs are in `ARCHITECTURE_RESEARCH.md`.
- Checked top-level and per-directory licenses. **AATM (`oldman-088/AATM`) has no LICENSE file, so its code must not be copied.**
- Verified the Phase 0 points for AATM, LangGraph, OpenHands and CAMEL, with file citations.
- Wrote ARCHITECTURE_RESEARCH, SOURCE_CODE_REUSE_AUDIT, DEPENDENCY_AUDIT, TECHNICAL_DECISIONS, SYSTEM_DESIGN and IMPLEMENTATION_STATUS.

**Decisions:** TD-001…TD-012 (npm + uv; pairing instead of embedded tokens; close codes; adapters as YAML; completion rule;
psycopg 3 for Postgres because of the LangGraph checkpointer; tool-declared risk for approvals; deterministic recovery; live-view spike; TS version check; dagre over elkjs; no AATM code copy).

**Reused code:** none. **New dependencies:** none installed (Phase 0 has no product code).

**Tests run:** none (Phase 0 has no product code). The DoD was checked manually: all documents exist, each repository claim cites a path, SHAs are recorded, and uninspected areas are listed.

**Known issues / open points:**
- AATM license: the owner may add one to allow reuse (TD-012).
- The OpenHands repository was restructured; the Appendix A GUI findings about it were not re-verified.
- TypeScript 7 and typescript-eslint compatibility must be checked in Phase 1 (TD-010).

**Next step:** Phase 1. Start with a spike on the live-view technique (TD-009), then the repository skeleton, `scripts/check.sh`, the mock provider and the bridge.
