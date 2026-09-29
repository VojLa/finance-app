# Accounts and liabilities modules

Type: module
Status: current
Owns: account, access and liability runtime layers
Code: `backend/python/app/modules/accounts/`, `backend/python/app/modules/liabilities/`, `src/modules/accounts/`
Update when: an account or liability layer, entry point or dependency changes

| Module                 | Responsibility                                                           | Main layers and entry points                                                        |
| ---------------------- | ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| `accounts`             | account lifecycle, membership, invitation and access policy              | `api.py`, `access.py`, `invitations.py`, `service.py`, `repository.py`, `models.py` |
| `liabilities`          | validate and persist dated liability evidence                            | `api.py`, manual/evidence services, writer and repositories                         |
| `src/modules/accounts` | account and liability contracts, clients, page state and server adapters | clients/contracts, request parsers/controllers, `server/*-api.ts`                   |

Both backend modules require the resolved identity and PostgreSQL. Liabilities require
an authorized account and feed valuation; they do not own net-worth aggregation.
Frontend modules preserve transport decimals and permissions but do not authorize.
Exact files remain in the [code inventory](../../map/generated/CODE-INVENTORY.md).
