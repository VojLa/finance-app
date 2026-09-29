# Documentation map

Type: reference
Status: current
Owns: routing between project, domain and generated maps
Code: whole repository and documentation generators
Update when: a map layer or generated inventory changes

This directory is the L0/L1 navigation layer for Codex and contributors.

- [`project-map/`](project-map/README.md) contains the L0 project maps.
- [`PROJECT-MAP.md`](PROJECT-MAP.md) is a compatibility path.
- [`domain-map/`](domain-map/README.md) contains one L1 map per domain.
- [`DOMAIN-MAP.md`](DOMAIN-MAP.md) is a compatibility path.
- [`generated/`](generated/README.md) contains deterministic inventories checked
  by `scripts/docs/`; do not edit or add manual inventories there.

## Ownership

Semantic directories own current rules. Numbered paths, `domains/evidence` and
`architecture/modules` are historical compatibility material and are not the
default reading path.
