# Repository map

Type: reference
Status: current
Owns: top-level implementation, automation and documentation locations
Code: repository root
Update when: a top-level runtime or tooling location changes

| Area                                 | Location                                                 |
| ------------------------------------ | -------------------------------------------------------- |
| Next.js UI and adapters              | `src/app/`, `src/components/`, `src/modules/`            |
| Python application                   | `backend/python/app/`                                    |
| Python tests                         | `backend/python/tests/`                                  |
| Migrations and schema evidence       | `backend/python/migrations/`, `backend/python/database/` |
| Rust experiment                      | `backend/rust/finance_engine/`                           |
| Frozen legacy schema archive         | `prisma/migrations/`                                     |
| Local import fixtures                | `test_imports/`                                          |
| Next.js and backend configuration    | root config files, `backend/python/pyproject.toml`       |
| CI workflows                         | `.github/workflows/`                                     |
| Contract and boundary tooling        | `scripts/`                                               |
| Documentation automation             | `scripts/docs/`                                          |
| Agent workflows and persistent rules | `.agents/`, `memory/codex_rules.md`, `AGENTS.md`         |
| Current technical docs               | `!docs/`                                                 |
| Future design                        | `!planning/`                                             |
| User guidance                        | `!user-docs/`                                            |
| Historical execution and audits      | `ChatGPT/`                                               |

See [tooling](../../development/tooling.md) for script authority and the
[CI matrix](../../testing/ci-matrix.md) for workflow ownership.

Dependency/cache/build directories such as `node_modules`, `.next`, `.uv-*`,
`.mypy_cache` and `.ruff_cache` are generated local state and are not documentation
or runtime source of truth. Import fixtures are test input and must not be copied into
documentation or logs.
