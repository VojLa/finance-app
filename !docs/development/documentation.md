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
