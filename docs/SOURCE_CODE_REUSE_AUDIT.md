# Source Code Reuse Audit

Every file copied or adapted from another project must be listed here (SPEC §3.4).

## Copied files

| Project | Component | Original file | License | Reuse method | Changes |
|---|---|---|---|---|---|
| — | — | — | — | — | — |

**No code has been copied as of Phase 0.**

## Reuse eligibility (from license check, Phase 0)

| Project | License (verified file) | May copy? | Planned reuse |
|---|---|---|---|
| AATM | **No LICENSE file** at `e90f2ef` | **No.** Design ideas only (protocol shape, state names, stop-rule concepts), re-implemented from scratch. The repository owner can add a license later; record that here before any copy. | Concepts: connector protocol, needs-human handling, plan DAG checks, verdict fallback |
| AATM → arena-auto-continue | MIT (per AATM `THIRD_PARTY_NOTICES.md`; upstream not cloned) | Only after cloning upstream and reading its LICENSE | None planned |
| LangGraph | MIT (`libs/*/LICENSE`) | Yes, but used as a **package dependency** | `langgraph`, `langgraph-checkpoint-sqlite`, `langgraph-checkpoint-postgres` (Phase 4) |
| OpenHands / software-agent-sdk | MIT | Yes | Ideas only (event shape, confirmation policy); no copy planned |
| DeerFlow | MIT (root); sub-licenses under `examples/` and `skills/` not read | Root code yes; sub-directories need a check | Ideas: live browser panel |
| AgentScope | Apache-2.0 | Yes, with NOTICE preservation | Ideas: tool renderers |
| AutoGen | Code MIT (`LICENSE-CODE`), docs CC-BY-4.0 | Code yes | Ideas: builder UX |
| ChatDev | Apache-2.0 | Yes | Ideas: schema-driven forms |
| CrewAI | MIT | Yes | Ideas: node drawer |
| CAMEL | Apache-2.0 | Yes | Ideas: failure strategies; optional adapter (Phase 7) as a dependency |
| Agno, MetaGPT, OpenManus | Apache-2.0 / MIT / MIT | Yes | None planned |
