# Generated documentation inventory

Type: reference
Status: current
Owns: navigation and regeneration rules for deterministic inventories
Code: `scripts/docs/generate_*.py`
Update when: a generated inventory or generator is added, removed or renamed

This directory contains deterministic generated files:
[code index](CODE-INVENTORY.md), [API inventory](API-INVENTORY.md),
[database inventory](DB-INVENTORY.md), [test inventory](TEST-INVENTORY.md),
and [module inventory](MODULE-INVENTORY.md). The code index links to one
inventory per source layer so generated documentation also remains short.

Run the matching script in [`scripts/docs/`](../../../scripts/docs/README.md)
to update an inventory, or run `python scripts/docs/check_docs.py` to verify
all generated files and local Markdown links. Do not manually edit generated
inventories.
