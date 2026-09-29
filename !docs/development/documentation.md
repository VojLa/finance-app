# Documentation workflow

Type: reference
Status: current
Owns: DOC IMPACT and documentation maintenance rules
Code: documentation roots and `scripts/docs/`
Update when: documentation ownership or checks change

After each change, decide whether it affects maps, current technical docs,
OpenAPI/generated inventories, user docs, ADR/planning, or nothing. Update only
the owning document. Keep exhaustive facts generated and semantic explanations
manual. Run `python scripts/docs/check_docs.py` before completion.

## Maintenance loop

1. Compare the changed code/API/model/test/tooling area with its generated inventory.
2. Open the L1 map and one owning domain; do not scan or rewrite unrelated docs.
3. Update the single semantic owner: domain/module, invariant, flow, API/data/testing,
   security or runbook.
4. Update project/domain maps only for changed ownership, entry point or dependency.
5. Regenerate only affected inventories through `scripts/docs`; never hand-edit them.
6. Run the documentation checker, metadata/orphan review and focused existence checks.
7. Delta-review the changed documents and their immediate incoming/outgoing links.

Use the [coverage contract](documentation-coverage.md) to decide completeness and the
[document types](document-types.md) to avoid duplicate owners. Historical files may
retain point-in-time evidence but must carry `Status: historical` and route readers to
current semantic documentation.
