# Documentation automation

This directory contains deterministic documentation tooling. It generates code,
OpenAPI, database/model, test, and module inventories plus `check_docs.py` for
freshness and local-link consistency checks.

Run from the repository root:

```powershell
python scripts/docs/generate_code_inventory.py
python scripts/docs/generate_api_inventory.py
python scripts/docs/generate_db_inventory.py
python scripts/docs/generate_test_inventory.py
python scripts/docs/generate_module_inventory.py
python scripts/docs/check_docs.py
```

Each generator accepts `--check` and writes only `!docs/map/generated/`. The
OpenAPI generator invokes `uv run` in `backend/python`, so it uses the same
application-derived contract as the TypeScript generator. Generated files are
versioned and never hand-edited. The checker also verifies local Markdown links,
the 500-line Markdown limit inside `!docs/`, and a `README.md` in every
`!docs/` directory. Manual technical documents are limited to 200 lines;
generated inventories are exempt and split deterministically when useful.
Every directory under `!docs`, `!planning`, and `!user-docs` requires a
`README.md`. Semantic maps and user documentation remain human-maintained.
