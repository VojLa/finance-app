# Repository tooling

Type: reference
Status: current
Owns: purpose and authority of executable repository maintenance tools
Code: `scripts/`, `scripts/docs/`, `backend/python/scripts/`, `package.json`
Update when: a script is added, removed or changes authority

| Tool                                         | Purpose                                                                            | Safety or authority                                |
| -------------------------------------------- | ---------------------------------------------------------------------------------- | -------------------------------------------------- |
| `generate-python-api-types.mjs`              | derive TypeScript transport types from FastAPI OpenAPI                             | generated output only; `--check` detects drift     |
| `check-typescript-boundary.mjs`              | enforce allowed TypeScript runtime boundaries                                      | policy is `typescript-boundary-policy.json`        |
| `scripts/docs/generate_*.py`                 | deterministic code, API, DB, module and test inventories                           | write only under `!docs/map/generated/`            |
| `scripts/docs/check_docs.py`                 | verify generated freshness, local links, README presence and manual `!docs` length | documentation CI entry point                       |
| `backend/python/scripts/check.py`            | backend Ruff, formatting, mypy and pytest gate                                     | read-only verification                             |
| `database_migrate.py`                        | Alembic check, upgrade and bootstrap entry point                                   | Alembic is the only migration owner                |
| `database_schema.py`, `sqlalchemy_schema.py` | schema artifact and runtime-model parity                                           | require PostgreSQL for live comparison             |
| `alembic_baseline.py`, `migration_policy.py` | verify inherited baseline and migration policy                                     | never mutate the frozen Prisma archive             |
| `export_openapi.py`                          | export the application-derived API contract                                        | source for generated clients and API inventory     |
| `seed_defaults.py`                           | idempotently initialize required default data                                      | requires an explicitly configured database         |
| `asset_alias.py`                             | inspect or create exact provider identities                                        | create-only, operator-controlled, supports dry run |
| `audit_exchange_rates.py`                    | read-only exchange-rate source audit                                               | never repairs or synthesizes evidence              |

Exact commands belong to [quality gates](../testing/quality-gates.md),
[data recovery](../data/migrations-and-recovery.md), and the relevant
[operations runbook](../operations/README.md).
