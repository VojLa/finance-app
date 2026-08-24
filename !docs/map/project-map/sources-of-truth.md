# Sources of truth map

| Question | Source |
| --- | --- |
| What is implemented? | [technical documentation](../../README.md) and runtime code/tests |
| What is planned? | [`!planning`](../../../!planning/README.md) |
| How should an AI task run? | [`AGENTS.md`](../../../AGENTS.md) and [`CHATGPT`](../../../CHATGPT/README.md) |
| What are the exact files/routes/models/tests? | [generated inventories](../generated/README.md) |
| What is the HTTP contract? | live FastAPI OpenAPI |
| What owns database schema changes? | Alembic and the ownership manifest |

When prose conflicts with code, tests or live OpenAPI, fix the owning document
in the same change.
