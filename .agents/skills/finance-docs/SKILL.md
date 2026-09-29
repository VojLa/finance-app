---
name: finance-docs
description: "Assess and update Finance App documentation after a change without duplicating current, planned, user-facing, historical, or generated information."
---

# Finance App documentation impact

Use at the end of implementation or for a documentation-only task. Update only the
owner whose truth changed.

## Ownership

| Location | Authority |
| --- | --- |
| `!docs/` | currently implemented architecture, domains, API, data, security, operations, tests, and development |
| `!planning/` | future scope, target design, roadmap, proposals, and durable decisions |
| `!user-docs/` | observable user behavior and troubleshooting |
| `!docs/map/generated/` | deterministic inventories; never hand-edit |
| `.agents/` | current Codex workflow, skills, model routing, and templates |
| `ChatGPT/` | historical execution and audit evidence only |

Semantic paths under `!docs/architecture`, `domains`, `api`, `data`, `testing`,
`security`, `operations`, `development`, and `reference` own current prose.
Numbered and evidence paths are historical compatibility routes.

## Impact decision

Record exactly which category changed:

1. project/domain map or module entry point;
2. current technical documentation or invariant;
3. OpenAPI or generated inventory;
4. user documentation;
5. ADR/planning decision;
6. active agent workflow under `.agents/`; or
7. no documentation.

A module boundary, entry point, dependency, source of truth, test location, or
recovery route updates its current semantic owner. A public behavior change updates
user docs only when the user can observe or act on it. A durable architectural
decision belongs in `!planning/decisions/` before or with implementation.

## Verification

Regenerate only affected inventories with `scripts/docs/`; do not copy exhaustive
lists into maintained prose. Run `python scripts/docs/check_docs.py`, the affected
generator's `--check`, and a delta review of changed documents and immediate links.
Historical files may retain old facts only when explicitly marked historical and
routed to the current owner.
