# Documentation coverage contract

Type: reference
Status: current
Owns: criteria for deciding whether the implemented repository is documented
Code: whole repository and `scripts/docs/`
Update when: a runtime area, generated inventory or documentation owner changes

Coverage has two layers. Generated inventories enumerate volatile facts; semantic
documents explain why those facts exist and how they interact. Manual documents do
not repeat complete file, endpoint, model or test lists.

| Repository concern                | Exhaustive evidence                                      | Semantic owner                                                 |
| --------------------------------- | -------------------------------------------------------- | -------------------------------------------------------------- |
| Python, TypeScript and Rust files | [code inventory](../map/generated/CODE-INVENTORY.md)     | project and domain maps                                        |
| Backend and frontend modules      | [module inventory](../map/generated/MODULE-INVENTORY.md) | domain `modules.md` files                                      |
| FastAPI operations and schemas    | [API inventory](../map/generated/API-INVENTORY.md)       | [API](../api/README.md) and domains                            |
| SQLAlchemy models and revisions   | [DB inventory](../map/generated/DB-INVENTORY.md)         | [data ownership](../data/README.md)                            |
| Python and frontend tests         | [test inventory](../map/generated/TEST-INVENTORY.md)     | domain matrices and [testing](../testing/README.md)            |
| CI and executable tooling         | repository files                                         | [CI matrix](../testing/ci-matrix.md) and [tooling](tooling.md) |
| Runtime recovery                  | executable commands and tests                            | [operations](../operations/README.md)                          |

An area is covered when it is present in the relevant generated inventory, routed
from L0 and L1, assigned to one semantic owner, linked to representative tests, and
has an explicit recovery route when it owns durable or operator-controlled work.

Empty or export-only namespace placeholders `src/modules/analytics`, `fx`, `holdings`,
`notifications`, `pricing`, `snapshots`, `users` and `wallet` remain inventory-only
until they acquire runtime behavior. Historical compatibility files are routed through
[documentation history](../history/README.md) and never own current rules.
