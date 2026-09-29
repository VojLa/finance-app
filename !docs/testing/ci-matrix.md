# Continuous-integration matrix

Type: testing
Status: current
Owns: CI workflow scope, prerequisites and verification responsibility
Code: `.github/workflows/*.yml`
Update when: a workflow trigger, environment or gate changes

| Workflow              | Primary scope                                    | Main evidence                                                                    | Prerequisites                                          |
| --------------------- | ------------------------------------------------ | -------------------------------------------------------------------------------- | ------------------------------------------------------ |
| `backend-python.yml`  | Python application, scripts and tests            | Ruff lint/format, mypy, pytest with coverage                                     | Python 3.12, locked `uv` dependencies                  |
| `database-schema.yml` | Alembic graph, schema artifacts and model parity | migration policy, clean PostgreSQL upgrade, schema checks and integration suites | PostgreSQL 16, `uv`, current Alembic head              |
| `frontend.yml`        | Next.js UI, adapters and transport boundary      | generated API check, boundary policy, Vitest, lint and TypeScript                | locked npm dependencies and exportable FastAPI OpenAPI |
| `docs.yml`            | documentation and source inventory               | generated freshness, local links, README and manual-length checks                | Python/`uv` for application-derived OpenAPI            |

The database workflow owns destructive schema operations only inside its disposable CI
database. Documentation CI runs for changes under documentation roots, application
source, documentation scripts and its own workflow. Push execution is configured for
`main`; pull requests provide branch validation.

No single workflow proves a cross-domain finance invariant. The owning domain matrix
identifies representative tests, and release/full review selects all affected workflows.
