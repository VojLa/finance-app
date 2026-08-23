# Finance App — Project Map (L0)

Read this after `AGENTS.md` and `memory/codex_rules.md`. It is a concise
routing layer, not a restatement of code. Select one row, read its L1 entry in
[`DOMAIN-MAP.md`](DOMAIN-MAP.md), then open the linked documentation and only
the few source and test files needed for the task.

## System boundary and authority

Finance App is a modular monolith:

```text
Browser → Next.js UI / same-origin adapters → FastAPI /api/v1 → PostgreSQL
                                                    │
                                      SQLAlchemy runtime + Alembic migrations
```

| Layer | Main location | Authority and boundary |
| --- | --- | --- |
| Browser UI | `src/app/`, `src/components/`, `src/modules/` | Presents typed server results. It owns no financial calculation, authorization, or persistence. |
| Browser-to-Python adapter | `src/app/api/`, `src/modules/*/server/`, `src/modules/python-api/` | Verifies a NextAuth session, performs narrow request/response validation, and mints internal server tokens. |
| Application and API | `backend/python/app/api/`, `app/auth/`, `app/modules/` | FastAPI/Pydantic contracts, business behavior, authorization, canonical financial workflows, and background orchestration. |
| Persistence | `backend/python/app/db/`, `migrations/`, `database/` | PostgreSQL is storage authority; SQLAlchemy is its runtime mapping; Alembic alone owns executable migrations. |
| Generated contract | `backend/python/scripts/export_openapi.py`, `scripts/generate-python-api-types.mjs`, `src/generated/python-api.ts` | FastAPI OpenAPI is the HTTP source; TypeScript transport types are generated and never manually edited. |
| Experimental calculation code | `backend/rust/finance_engine/` | Prototype only; it is not called by Python and is not a source of financial truth. |

## Read order

1. `AGENTS.md` → `memory/codex_rules.md`.
2. This L0 map → the relevant L1 domain section.
3. Current implementation documentation in `!docs/`; accepted or future design
   in `!planning/`.
4. Three to eight relevant API, service, repository, model, adapter, and test
   files.

The numbered directories in `!docs/` remain the current implementation
documentation during the semantic-folder migration. Code, tests, and live
OpenAPI are the immediate runtime truth when documentation conflicts.

## Domain routing

| Domain group | Choose it when changing… | Backend ownership | Browser/adapters |
| --- | --- | --- | --- |
| Identity and access | registration, credentials, session bridge, protected request identity | `app/auth/`, `app/api/` | `src/lib/auth/`, `src/app/(auth)/`, `src/app/api/auth/` |
| Accounts and liabilities | account metadata, membership, invitations, archive/restore, liability balances | `modules/accounts/`, `modules/liabilities/` | `modules/accounts/`, `app/api/accounts/`, `app/accounts/` |
| Transactions, categories, budgets | manual cash ledger, category hierarchy, monthly plans, operational cash flow | `transactions/`, `categories/`, `budgets/`, `operational_dashboard/` | matching `src/modules/`, `app/transactions/`, `app/categories/`, `app/budget/`, `app/dashboard/` |
| Imports and durable jobs | CSV boundaries, parser normalization, reconciliation, retries, publication fencing | `imports/`, `jobs/` | `modules/imports/python/`, `app/api/import/`, `app/imports/` |
| Investments and canonical state | manual investment commands, events/movements, canonical revisions, Holding rebuild | `investments/`, `canonical_state/`, `holdings/` | `modules/investments/`, `app/portfolio/add/`, `app/api/portfolio/transactions/` |
| Market identity, prices, and FX | aliases/listings, provider data, direct prices/FX, market requirements | `asset_aliases/`, `market_data/`, `prices/`, `fx/` | No active client-side finance authority; presentation is downstream. |
| Valuation, snapshots, and current value | baseline lineage, current projection, account/net-worth snapshots, coordinated refresh | `snapshots/`, `daily_baselines/`, `current_value/`, `net_worth/`, `snapshot_refresh/` | `modules/python-api/`, snapshot workflow routes |
| Portfolio, dashboard, and history | authorized read projections, charts, account presentation, dashboard cards | `portfolio/`, `portfolio_snapshot/`, `dashboard_snapshot/`, `portfolio_history/` | `modules/portfolio/`, `modules/dashboard/`, `app/portfolio/`, `app/dashboard/` |
| Persistence and platform | database model, schema artifact, migration, settings, logging, shared serialization | `app/db/`, `migrations/`, `database/`, `app/config/`, `app/shared/` | `src/lib/` technical utilities only |

## Cross-domain dependency flow

```text
Identity → Accounts/access
              ├─→ Transactions / Categories / Budgets → Operational dashboard
              ├─→ Imports → Jobs → canonical writes ─┐
              └─→ Investments → Canonical state → Holdings ┤
Asset aliases → Market prices and direct FX ────────────────┤
                                                          ↓
                     Snapshots / baselines / current value / net worth
                                                          ↓
                         Portfolio · Dashboard · History read models
```

The arrows show allowed business-data flow, not permission to bypass a domain's
public service boundary. Imports, manual commands, and account actions all
enforce authorization inside Python.

## Repository sources of truth

| Concern | Read first |
| --- | --- |
| Current architecture, runtime behavior, technical constraints | [`!docs/README.md`](../README.md) and the linked domain documentation |
| Future scope, proposals, accepted design before implementation | [`!planning/README.md`](../../!planning/README.md) and its decisions |
| Task sizing, implementation, review, and templates | [`CHATGPT/README.md`](../../CHATGPT/README.md) |
| Persistent finance and import invariants | [`memory/codex_rules.md`](../../memory/codex_rules.md) |
| Exact source/module/test lists | [`generated/`](generated/README.md) inventories |

## Global invariants

- Money uses `Decimal`, explicit currency, and explicit rounding; floats are
  never financial truth.
- Account-level primary presentation uses `Account.currency`; aggregate
  portfolio/dashboard/net-worth values use `User.baseCurrency`. Native currency
  breakdowns remain evidence, not substitute totals.
- Event-date direct FX is used for historical events; snapshot/current direct
  market evidence is used for valuation. Do not synthesize inverse or cross FX.
- Canonical finance writes are server-owned, atomic as documented, idempotent
  where retried, and carry revision lineage. Holdings and snapshots are derived
  evidence, not a replacement for canonical history.
- Python is the final authentication, authorization, and account-isolation
  boundary. Browser code cannot calculate a financial fallback.
- Imports and provider payloads are untrusted. Do not log or expose raw files,
  tokens, sensitive financial payloads, or internal failures.
- Alembic alone owns executable application migrations. The Prisma SQL history
  is immutable archive material.

## Map maintenance

Update this L0 map when a domain is added/removed, an authority or cross-domain
dependency changes, or a top-level entry point moves. Update the L1 map when a
domain's concrete files, tests, source of truth, or invariants change. The
deterministic inventories are refreshed by `scripts/docs/`, never by hand.
