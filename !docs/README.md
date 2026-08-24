# Finance App technical documentation

Type: reference
Status: current
Owns: root navigation for implemented technical documentation
Code: whole repository
Update when: a top-level documentation owner changes

Implemented behavior lives here. Future design is in [`!planning`](../!planning/README.md), user guidance in [`!user-docs`](../!user-docs/README.md), and milestone evidence in [`CHATGPT`](../CHATGPT/README.md).

| Need | Start here |
| --- | --- |
| Find a subsystem | [Project maps](map/project-map/README.md) → [domain maps](map/domain-map/README.md) |
| Understand business ownership | [Domains](domains/README.md) |
| Understand boundaries, flows or invariants | [Architecture](architecture/README.md) |
| Change HTTP behavior | [API](api/README.md) |
| Change schema or persistence | [Data](data/README.md) |
| Select verification | [Testing](testing/README.md) |
| Handle auth or sensitive input | [Security](security/README.md) |
| Run or recover the app | [Operations](operations/README.md) |
| Follow implementation workflow | [Development](development/README.md) |
| Look up a shared term | [Reference](reference/README.md) |
| Inspect exhaustive facts | [Generated inventories](map/generated/README.md) |
| Read historical evidence | [History](history/README.md) |

Read `AGENTS.md` → project maps → one domain map → only the relevant invariant,
flow, code and tests. Runtime code, tests and live OpenAPI prevail over stale prose.
