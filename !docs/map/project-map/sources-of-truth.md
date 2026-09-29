# Sources of truth map

Type: reference
Status: current
Owns: precedence between code, generated facts, current docs and planning
Code: documentation roots and runtime contracts
Update when: documentation or runtime authority changes

| Question                                      | Source                                                                        |
| --------------------------------------------- | ----------------------------------------------------------------------------- |
| What is implemented?                          | [technical documentation](../../README.md) and runtime code/tests             |
| What is planned?                              | [`!planning`](../../../!planning/README.md)                                   |
| How should a Codex task run?                  | [`AGENTS.md`](../../../AGENTS.md) and [`.agents`](../../../.agents/README.md) |
| What are the exact files/routes/models/tests? | [generated inventories](../generated/README.md)                               |
| What is the HTTP contract?                    | live FastAPI OpenAPI                                                          |
| What owns database schema changes?            | Alembic and the ownership manifest                                            |

When prose conflicts with code, tests or live OpenAPI, fix the owning document
in the same change.

[`ChatGPT`](../../../ChatGPT/README.md) is historical execution evidence and is
not an active instruction source.
