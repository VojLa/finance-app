# Finance App — Domain Map (L1)

Use this map after selecting a domain in [`PROJECT-MAP.md`](PROJECT-MAP.md).
Each section identifies the current implementation boundary, not an aspirational
module. Python `api.py` files are thin FastAPI adapters; Python
service/repository/writer/reader layers own behavior and persistence access.
`src/modules/` and `src/app/api/` are browser-facing contracts and adapters,
not financial sources of truth.

## Detailed module documents

Read the matching document for detailed architecture and invariants:
[identity](../domains/identity-and-api.md),
[accounts](../domains/accounts-and-liabilities.md),
[transactions](../domains/transactions-and-categories.md),
[budgets](../domains/budgets-and-operational-dashboard.md),
[imports](../domains/imports-and-background-jobs.md),
[investments](../domains/investments-canonical-state-and-holdings.md),
[market data](../domains/market-data-prices-and-fx.md),
[valuation](../domains/snapshots-baselines-current-value-and-net-worth.md),
[read models](../domains/portfolio-dashboard-and-history.md),
[persistence](../domains/persistence-migrations-and-runtime.md), and
[frontend](../domains/frontend-and-experimental-rust.md).

## 1. Identity and API boundary

**Purpose and truth.** User credentials, trusted internal session token
validation, request identity, and public FastAPI/OpenAPI contracts. Credentials
and authorization are Python-owned; NextAuth is the browser session boundary.

- **Entry points:** `backend/python/app/api/router.py`, `app/auth/api.py`,
  `app/main.py`; Next auth routes in `src/app/api/auth/`.
- **Layers:** `app/auth/{models,service,repository,token,dependencies}.py`,
  `app/api/`, `src/lib/auth/`, and `src/modules/python-api/server/`.
- **Dependencies:** users/accounts persistence; every protected domain consumes
  the resolved Python principal.
- **Tests:** `test_auth_*.py`, `test_request_context.py`,
  `src/lib/auth.test.ts`, and `src/modules/python-api/**/*.test.*`.
- **Documentation:** [security](../01-architecture/04-security.md),
  [API conventions](../03-api/01-conventions.md), and
  [technical overview](../01-architecture/01-technical-overview.md).
- **Invariants:** internal tokens never reach the browser; callers cannot select
  a principal; Python enforces account isolation; public errors omit credentials,
  raw upstream responses, and internal detail.

## 2. Accounts, membership, and liabilities

**Purpose and truth.** `Account`, account membership/invitation, and immutable
liability-balance evidence are PostgreSQL records operated through the Python
account and liability modules. `Account.currency` is the intended account
presentation currency.

- **Entry points:** `modules/accounts/api.py`, `accounts/invitations.py`,
  `modules/liabilities/api.py`; Next routes under `src/app/api/accounts/`.
- **Layers:** `accounts/{models,service,repository}.py`,
  `liabilities/{models,repository,writer}.py`, DB models
  `app/db/models/{accounts,liabilities}.py`; browser `src/modules/accounts/`.
- **Dependencies:** identity/membership; transactions, imports, investments,
  snapshots, and read projections refer to accounts.
- **Tests:** `test_accounts_*`, `test_account_access.py`,
  `test_account_membership_*`, `test_account_invitations*`,
  `test_liability_*`, and `src/modules/accounts/**/*.test.*`.
- **Documentation:** [modules](../01-architecture/02-modules.md),
  [domain model](../02-domain-model.md), and
  [API conventions](../03-api/01-conventions.md).
- **Invariants:** Python is final role/account check; account type is immutable
  after creation; archive is not destructive deletion; liabilities are positive,
  effective-at observations selected explicitly by valuation.

## 3. Transactions and categories

**Purpose and truth.** Canonical cash transactions and category hierarchy.
PostgreSQL transaction/category rows are authoritative; a successful manual
cash command advances canonical account revision exactly as documented.

- **Entry points:** `modules/transactions/api.py`, `modules/categories/api.py`;
  Next routes `src/app/api/transactions/` and `src/app/api/categories/`.
- **Layers:** both modules use `models.py`, `service.py`, `repository.py`;
  transaction visibility is `transactions/operational_visibility.py`; browser
  contracts/clients are in `src/modules/transactions/` and `categories/`.
- **Dependencies:** identity, account access, and category ownership.
  Operational dashboard reads transactions; valuation consumes applicable
  canonical events and revisions.
- **Tests:** `test_transactions_categories*`,
  `test_operational_transaction_visibility*`, `test_categories_*`, and
  TypeScript tests in the matching two browser modules.
- **Documentation:** [domain model](../02-domain-model.md),
  [API conventions](../03-api/01-conventions.md), and
  [coding standards](../04-development/03-coding-standards.md).
- **Invariants:** public amounts are exact decimal strings; income is positive
  and expense negative in canonical storage; writes are idempotent and account
  authorized; category defaults are immutable and custom hierarchy rejects
  cycles and inaccessible parents.

## 4. Budgets and operational dashboard

**Purpose and truth.** Monthly budget plans plus read-only operational
cash-flow/category/trend projections. Budget plans and transactions are their
authorities; operational data never reconstructs or replaces snapshot finance.

- **Entry points:** `modules/budgets/api.py`, `modules/operational_dashboard/api.py`;
  Next `src/app/api/budget/`, `src/app/api/dashboard/`.
- **Layers:** `budgets/{models,service,repository}.py`,
  `operational_dashboard/{models,service,repository}.py`; browser
  `src/modules/budgets/` and `src/modules/dashboard/`.
- **Dependencies:** accounts, categories, transaction visibility, and identity.
- **Tests:** `test_budgets_operational_dashboard*`,
  `test_operational_transaction_visibility*`, budget client tests, and
  `src/modules/dashboard/operational-dashboard-model.test.ts`.
- **Documentation:** [modules](../01-architecture/02-modules.md) and
  [technical overview](../01-architecture/01-technical-overview.md).
- **Invariants:** budgets replace one scoped monthly plan atomically; optional
  rollover reads only persisted prior evidence; operational and snapshot-finance
  states/errors remain independent.

## 5. Imports and durable background jobs

**Purpose and truth.** Import batches/rows/issues and durable job state
coordinate untrusted file intake through canonical posting and guarded
publication. Import evidence and job records are persisted; parser output is
not a portfolio authority.

- **Entry points:** `modules/imports/api.py`, `modules/jobs/api.py`,
  `jobs/worker.py`, `jobs/import_executor.py`; Next routes in
  `src/app/api/import/`; browser code `src/modules/imports/python/`.
- **Layers:** `imports/{models,service,repository}.py`, source parsers under
  `imports/`, and `jobs/{models,lifecycle,service,repository,worker,publication_service}.py`;
  DB models `imports.py`, `background_jobs.py`, `publication_targets.py`.
- **Dependencies:** account authorization, asset aliases, transaction/investment
  canonical writers, holdings rebuild, market evidence, and snapshot refresh.
- **Tests:** `test_import_*`, `test_raiffeisenbank_*`, `test_trading212_*`,
  `test_anycoin_*`, `test_background_job_*`,
  `test_durable_import_job_executor.py`, plus `tests/fixtures/imports/`.
- **Documentation:** [import overview](../02-imports/01-overview.md),
  [parser contract](../02-imports/02-parser-contract.md),
  [supported sources](../02-imports/03-supported-sources.md), and
  [technical overview](../01-architecture/01-technical-overview.md).
- **Invariants:** files/providers are untrusted; raw input is not leaked;
  duplicate/replayed work cannot duplicate canonical finance; multi-file work
  post-processes once per logical account/source batch; incomplete publication
  stays fenced behind last complete evidence; unsupported rows are parse issues.

## 6. Investments, canonical state, and holdings

**Purpose and truth.** Investment events/movements are canonical financial
history. Account canonical state records committed lineage; Holdings is a
derived current projection, never alternate history.

- **Entry points:** `modules/investments/api.py`, `modules/holdings/api.py`;
  browser manual-add/symbol paths use `src/app/portfolio/add/`,
  `src/app/api/portfolio/transactions/`, and `src/modules/investments/`.
- **Layers:** `investments/{models,service,repository}.py`,
  `holdings/{models,projection,rebuild_service,repository}.py`,
  `canonical_state/{service,repository}.py`; DB models
  `ledger.py`, `holdings.py`, `canonical_lineage.py`.
- **Dependencies:** account access, asset identity, import posting; market
  evidence and snapshot orchestration consume its derived state.
- **Tests:** `test_manual_investments*`, `test_holding_*`,
  `test_canonical_state.py`, `test_empty_investment_holding_revision*`,
  `test_unknown_investment_cost_basis*`, and investment client tests.
- **Documentation:** [domain model](../02-domain-model.md),
  [modules](../01-architecture/02-modules.md), and the
  [cost-basis decision](../../!planning/decisions/0010-multi-currency-holding-cost-basis.md).
- **Invariants:** an investment command writes one complete event/movement set
  atomically, advances lineage once, and rebuilds Holdings; exact idempotent
  replay is safe while payload reuse conflicts; no empty event or client-owned
  Holding calculation is valid.

## 7. Asset aliases, market data, prices, and FX

**Purpose and truth.** Asset/provider identity and persisted direct price/FX
observations are reference evidence for valuation. They do not own user
holdings, event history, or portfolio totals.

- **Entry points:** operator tooling `backend/python/scripts/asset_alias.py`
  and `audit_exchange_rates.py`; application services are consumed by
  snapshot refresh, not a browser finance route.
- **Layers:** `asset_aliases/{models,service,repository}.py`,
  `market_data/{models,requirements,service,writer}.py` and
  `market_data/history/`, `prices/providers/`, `fx/`; DB models
  `assets.py`, `prices.py`.
- **Dependencies:** aliases resolve asset/provider identity; snapshots/current
  value request exact requirements; imports/investments reference known assets.
- **Tests:** `test_asset_alias_*`, `test_market_data_*`,
  `test_market_evidence_*`, `test_*price_*`, `test_*fx_*`,
  `test_exchange_rate_audit_script.py`, and provider-specific tests.
- **Documentation:** [FX reconciliation](../04-development/04-fx-reconciliation.md),
  [domain model](../02-domain-model.md), and
  [implementation decisions](../05-decisions/).
- **Invariants:** provider identity is explicit and immutable; valuation uses
  selected persisted direct observations; no inverse, triangulated, synthetic,
  stale, future, or wrong-source evidence is silently accepted; market data is
  never user-specific business state.

## 8. Snapshots, daily baselines, current value, and net worth

**Purpose and truth.** Snapshot records, canonical boundaries, daily baselines,
current projections, and net-worth aggregation provide exact valuation evidence.
Canonical transactions/events/liabilities remain business history; snapshots are
derived but immutable once written.

- **Entry points:** `modules/snapshots/api.py`, `current_value/api.py`,
  `net_worth/api.py`, `snapshot_refresh/api.py`; browser access is through
  bodyless Next snapshot-workflow routes.
- **Layers:** `snapshots/{models,calculation,writer,writer_repository}.py`, `daily_baselines/`,
  `current_value/{models,service,repository}.py`,
  `net_worth/{models,writer,repository}.py`, and
  `snapshot_refresh/{models,plan,executor,repository}.py`; DB models
  `snapshots.py`, `canonical_lineage.py`, `publication_targets.py`.
- **Dependencies:** accounts/liabilities, canonical state/Holdings, selected
  market evidence, durable import fences, and account membership.
- **Tests:** `test_account_snapshot_*`, `test_snapshot_*`,
  `test_daily_baseline_*`, `test_current_value_*`, `test_net_worth_*`,
  `test_r10b*`, `test_r10d*`, `test_r10e2_canonical_current_money.py`,
  and `test_snapshot_refresh_*`.
- **Documentation:** [domain model](../02-domain-model.md),
  [data flow](../01-architecture/03-data-flow.md),
  [technical overview](../01-architecture/01-technical-overview.md), and
  [derived-read-model decision](../05-decisions/0004-derived-read-models.md).
- **Invariants:** primary aggregate snapshots use user base currency; an
  account-currency companion is explicit evidence, not read-time conversion;
  daily baselines name canonical inclusion; current value is ephemeral
  baseline-plus-forward projection and never fabricates historical points.

## 9. Portfolio, dashboard snapshots, and portfolio history

**Purpose and truth.** Authorized read projections turn snapshot/current-value
evidence into portfolio, financial dashboard, and historical responses. They
own no alternate financial arithmetic or persistence truth.

- **Entry points:** `portfolio/api.py`,
  `portfolio_snapshot/{api,multi_account_api}.py`,
  `dashboard_snapshot/api.py`, `portfolio_history/api.py`; Next routes
  `snapshot-workflow/portfolio`, `snapshot-workflow/dashboard`, and
  `portfolio/history`; pages `src/app/portfolio/`, `src/app/dashboard/`.
- **Layers:** `portfolio/{models,service,repository}.py`,
  `portfolio_snapshot/{models,reader,repository}.py`,
  `dashboard_snapshot/{models,projection}.py`,
  `portfolio_history/{models,service,repository,selection}.py` plus
  generation/invalidation/job/scheduler submodules; browser
  `src/modules/portfolio/` and `src/modules/dashboard/`.
- **Dependencies:** accounts/access, snapshot/current-value/net-worth evidence,
  background publication fences, and persisted history-generation metadata.
  Operational dashboard remains section 4.
- **Tests:** `test_portfolio_*`,
  `test_authorized_portfolio_snapshot_reader.py`,
  `test_dashboard_snapshot_projection.py`, `test_portfolio_history_*`,
  `test_3q_portfolio_history_schema_migration_integration.py`, plus frontend
  portfolio/dashboard tests.
- **Documentation:** [technical overview](../01-architecture/01-technical-overview.md),
  [domain model index](../02-domain-model.md), and the matching
  [architecture history evidence](../architecture/modules/snapshot-backed-portfolio-history.md).
- **Invariants:** browser state preserves decimal strings and does not total,
  price, FX-convert, rank, or fall back to legacy finance; account presentation
  and aggregate primary lineage never mix; history cannot overwrite current
  financial state.

## 10. Persistence, migrations, configuration, and shared runtime

**Purpose and truth.** This technical domain owns physical mappings, database
lifecycle, configuration, logging, error/number serialization, and request
context. It is infrastructure, not a home for new business rules.

- **Entry points:** `app/main.py`, `app/lifespan.py`, `app/db/connection.py`,
  `scripts/database_migrate.py`, `scripts/database_schema.py`, and Alembic
  `migrations/env.py`.
- **Layers:** `app/db/{base,connection,health,url,models}/`,
  `app/config/settings.py`, `app/shared/`, `backend/python/migrations/`,
  `backend/python/database/`; frontend technical utilities are `src/lib/`.
- **Dependencies:** all Python domains use these facilities. This domain must
  not depend on a business module merely to host domain behavior.
- **Tests:** `test_database_*`, `test_sqlalchemy_*`, `test_alembic_*`,
  `test_migration_policy.py`, `test_settings.py`, `test_errors.py`,
  `test_request_context.py`, and migration integration tests.
- **Documentation:** [database README](../../backend/python/database/README.md),
  [technical overview](../01-architecture/01-technical-overview.md),
  [database ownership decision](../05-decisions/0003-database-schema-ownership.md),
  and [local setup](../04-development/01-local-setup.md).
- **Invariants:** application startup performs no DDL/migration; Alembic is the
  only executable migration owner; SQLAlchemy parity and revision schema
  artifacts are checked; shared code remains technical, never an unowned
  business module.

## 11. Frontend presentation and experimental Rust

**Purpose and truth.** Next.js pages/components render server-owned contracts;
generic UI, chart, date, decimal, file, logging, and validation helpers support
presentation. Rust is an isolated prototype workspace.

- **Entry points:** `src/app/`, `src/components/`, `src/app/providers.tsx`,
  `src/lib/`; Rust `backend/rust/finance_engine/`.
- **Layers:** `src/components/{charts,forms,layout,portfolio,tables,ui}/`,
  `src/lib/{auth,dates,decimal,files,logging,validation}/`, and generated
  transport `src/generated/python-api.ts`. The top-level browser folders
  `analytics`, `fx`, `holdings`, `notifications`, `pricing`,
  `snapshots`, `users`, and `wallet` currently contain only UI scaffolding
  or exports; they create no second runtime domain authority.
- **Dependencies:** typed browser contracts and API adapters only; it must not
  import Python persistence or duplicate finance services.
- **Tests:** page/component tests under `src/app/**/*.test.*`,
  `src/components/**/*.test.*`, `src/lib/**/*.test.*`, module tests in the
  generated inventory; Rust uses `cargo test` when changed.
- **Documentation:** [technical overview](../01-architecture/01-technical-overview.md),
  [coding standards](../04-development/03-coding-standards.md), and
  [TypeScript boundary policy](../../scripts/typescript-boundary-policy.json).
- **Invariants:** financial values remain exact strings until a leaf-only
  presentation conversion; a component cannot become finance, FX, account
  authorization, or persistence authority; generated API types are not edited;
  Rust requires explicit boundary/parity design before becoming runtime.

## Cross-domain rules

1. New import: parser/normalization → import evidence/job → canonical writer →
   derived Holding/snapshot publication; never directly into a read model.
2. New financial event: canonical event/movement and lineage first, then
   derived projections and presentation; never only frontend arithmetic.
3. New market provider: asset/provider identity and direct market evidence
   first; snapshots consume that evidence rather than provider responses.
4. New user view: server read contract if needed, then thin browser adapter and
   presentation. It cannot silently calculate a second financial definition.
5. Schema change: update SQLAlchemy mapping, Alembic revision, revision schema
   artifact, and parity tests under database ownership rules.

## Detailed source indexes

Use deterministic inventories for complete lists rather than expanding this
semantic map into a file catalogue:

- [modules](generated/MODULE-INVENTORY.md)
- [production code](generated/CODE-INVENTORY.md)
- [API operations](generated/API-INVENTORY.md)
- [database and model files](generated/DB-INVENTORY.md)
- [tests](generated/TEST-INVENTORY.md)
