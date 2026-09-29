# Platform testing

Type: testing
Status: current
Owns: representative schema, configuration, health and architecture-boundary verification
Code: platform tests and all CI workflows
Update when: platform risks, tools or representative suites change

| Risk                                 | Layer                    | Local evidence                                               | CI owner                   |
| ------------------------------------ | ------------------------ | ------------------------------------------------------------ | -------------------------- |
| Schema or migration drift            | PostgreSQL/migration     | Alembic, database schema and SQLAlchemy parity tests         | `database-schema.yml`      |
| Invalid environment/readiness        | configuration/runtime    | `test_settings.py`, `test_database_url.py`, `test_health.py` | `backend-python.yml`       |
| Unsafe errors/logging                | shared infrastructure    | `test_errors.py`, `test_request_context.py`                  | `backend-python.yml`       |
| TypeScript becomes finance authority | architecture boundary    | TypeScript boundary and Prisma-removal tests                 | `frontend.yml`             |
| Generated API or docs drift          | deterministic generation | API type and documentation checks                            | `frontend.yml`, `docs.yml` |
| Rust acquires runtime authority      | architecture boundary    | code/repository review and inventories                       | full review gate           |
