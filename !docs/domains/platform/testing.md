# Platform testing

| Risk | Layer | Evidence |
| --- | --- | --- |
| Schema drift | migration/CI | database schema and Alembic tests |
| Runtime owner regression | architecture | Prisma-removal and boundary tests |
| Generated contract drift | OpenAPI/CI | Python API generation checks |
