# Identity and access modules

Type: module
Status: current
Owns: identity runtime layers and their allowed dependencies
Code: `backend/python/app/auth/`, `backend/python/app/api/`, `src/modules/auth/`, `src/modules/python-api/`
Update when: an identity entry point, layer or dependency changes

| Module                   | Responsibility                                                                 | Main layers and entry points                                                                  |
| ------------------------ | ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| `app/auth`               | credentials, principals, internal tokens and protected dependencies            | `api.py`, `dependencies.py`, `service.py`, `repository.py`, `token.py`, validation and models |
| `app/api`                | versioned router composition and health transport                              | `router.py`, `routes/health.py`                                                               |
| `src/modules/auth`       | server-only browser authentication adapter                                     | `server/auth-api.ts`                                                                          |
| `src/modules/python-api` | authenticated transport, configuration, errors and generated-contract adapters | client, transport, token, snapshot and history adapters                                       |

`app/auth` may depend on shared configuration, database and error infrastructure.
Business modules consume the resolved principal but cannot implement alternate
credential or token rules. Next.js adapters may transport identity but cannot choose
a principal. Exact files remain in the [code inventory](../../map/generated/CODE-INVENTORY.md).
