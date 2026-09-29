# Quality gates

Type: testing
Status: current
Owns: executable verification commands and their scope
Code: `package.json`, `backend/python/scripts/check.py`, CI workflows
Update when: command, dependency or CI gate changes

| Scope            | Command                                                                                |
| ---------------- | -------------------------------------------------------------------------------------- |
| Python focused   | `uv run pytest <test path>` from `backend/python`                                      |
| Python static    | `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app scripts tests` |
| Python full      | `uv run python scripts/check.py`                                                       |
| TypeScript tests | `npm.cmd test`                                                                         |
| TypeScript types | `npx.cmd tsc --noEmit`                                                                 |
| TypeScript lint  | `npm.cmd run lint`                                                                     |
| Documentation    | `python scripts/docs/check_docs.py`                                                    |

PostgreSQL integration requires a dedicated `DATABASE_URL`. Do not run
`npm run build` while `next dev` owns the `.next` cache.

Run focused checks before module/domain checks. Use the complete Python, frontend,
database-schema or documentation gate only when the changed slice reaches that
boundary. CI ownership and triggers are in the [CI matrix](ci-matrix.md).
