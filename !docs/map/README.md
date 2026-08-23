# Documentation map

This directory is the L0/L1 navigation layer for Codex and contributors.

- [`PROJECT-MAP.md`](PROJECT-MAP.md) is the L0 project entry point: read it after
  `AGENTS.md` and before opening broad documentation or source trees.
- [`DOMAIN-MAP.md`](DOMAIN-MAP.md) is the L1 domain index and routes to the most
  relevant current documentation and code boundaries.
- [`generated/`](generated/README.md) is reserved for deterministic inventories.
  Its files will be created and checked by `scripts/docs/` in the next V1 step;
  do not add manual inventories there.

## Migration status

The implemented documentation uses short semantic indexes and split module
documents. Follow the root `README.md`, then this map, then the target folder's
`README.md`. `02-domain-model.md` and `01-architecture/02-modules.md` are
redirect indexes; their detailed material is in `domains/evidence/` and
`architecture/modules/`.
