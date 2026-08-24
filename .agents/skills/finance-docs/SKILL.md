---
name: finance-docs
description: Maintain Finance App project maps and documentation through scoped impact analysis, preserving the distinction between planned, implemented, user-facing, and generated content.
---

# Finance App documentation workflow

Use this skill after a relevant implementation or documentation change. Update only documentation whose truth changes; do not rewrite unrelated material.

## Documentation ownership

| Location | Owns |
| --- | --- |
| `!planning/` | Future scope, roadmap, target architecture, proposals, and decisions before implementation. |
| `!docs/` | The currently implemented technical system: architecture, domains, data flow, API, database, security, development, tests, invariants, and implementation-facing decisions. |
| `!user-docs/` | End-user instructions, feature explanations, troubleshooting, and FAQ without implementation detail. |
| `!docs/map/generated/` | Deterministic inventories only. Never hand-edit generated output. |

Semantic paths under `!docs/architecture`, `domains`, `api`, `data`, `testing`, `security`, `operations`, `development`, and `reference` own current documentation. Numbered paths and evidence folders are historical compatibility routes; do not add current rules to them.

## Documentation impact

At the end of a change, decide explicitly whether it affects:

1. Project or domain map;
2. implemented technical documentation;
3. OpenAPI/API inventory;
4. user documentation;
5. ADR/planning decision; or
6. no documentation.

Record the result in the handoff. A changed module boundary, entry point, dependency, test location, or source of truth updates the relevant map. A public behavior change needs user documentation only when an end user can observe or act on it. A durable architectural decision belongs in `!planning/decisions/` before or with the implementation.

## Generated material and checks

Prefer deterministic scripts under `scripts/docs/` for code, API, database/model, test, and module inventories. Generated files must carry an auto-generated notice and be reproducible by their script. Before claiming generated output is current, run its check mode. Link checks and existence checks belong in `scripts/docs/check_docs.py` when that tooling is introduced.

Use concise, source-linked prose for semantic documentation. Avoid documenting trivial functions or copying code inventories into human-maintained maps.
