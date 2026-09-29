# Platform modules

Type: module
Status: current
Owns: shared Python runtime, persistence, frontend shell and experiment boundaries
Code: `backend/python/app/`, `src/app/`, `src/lib/`, `backend/rust/finance_engine/`
Update when: shared runtime, persistence or frontend-shell boundaries change

| Area                 | Responsibility                                                    | Main entry points                              |
| -------------------- | ----------------------------------------------------------------- | ---------------------------------------------- |
| application assembly | FastAPI factory, lifespan and router composition                  | `app/main.py`, `lifespan.py`, `api/router.py`  |
| configuration        | validated environment settings                                    | `app/config/settings.py`                       |
| persistence          | connection lifecycle, health and complete model mapping           | `app/db/connection.py`, `health.py`, `models/` |
| shared Python        | exact arithmetic, serialization, errors, logs and request context | `app/shared/`                                  |
| Next.js shell        | layouts, providers, pages and same-origin routes                  | `src/app/`                                     |
| browser utilities    | auth, formatting, refresh serialization and narrow utilities      | `src/lib/`                                     |
| Rust experiment      | isolated finance-engine experiment                                | no runtime authority or production dependency  |

Business rules remain in domain modules. Empty `analytics`, `notifications` and
`users` frontend namespaces export nothing and stay inventory-only. Exact files are
in the [code inventory](../../map/generated/CODE-INVENTORY.md).
