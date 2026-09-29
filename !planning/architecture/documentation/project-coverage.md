# Documentation project coverage

Type: reference
Status: implemented
Owns: mapování skutečných subsystémů na budoucí doménové dokumenty
Code: `src`, `backend/python`, `backend/rust`, databáze, scripts a CI
Update when: vznikne, zanikne nebo změní autoritu runtime subsystém

## Domény a runtime moduly

| Doména                       | Runtime moduly a hranice                                                         |
| ---------------------------- | -------------------------------------------------------------------------------- |
| Identity and access          | `auth`, společná `api`, NextAuth a session adapter                               |
| Accounts                     | `accounts`                                                                       |
| Liabilities                  | `liabilities`                                                                    |
| Cash flow                    | `transactions`, `categories`, `budgets`, `operational_dashboard`                 |
| Imports and jobs             | `imports`, `jobs`, parser/provider boundaries                                    |
| Investments                  | `investments`, `canonical_state`, `holdings`                                     |
| Market identity and evidence | `asset_aliases`, `market_data`, `prices`, `fx`                                   |
| Valuation                    | `snapshots`, `daily_baselines`, `current_value`, `net_worth`, `snapshot_refresh` |
| Portfolio read models        | `portfolio`, `portfolio_snapshot`, `dashboard_snapshot`                          |
| Portfolio history            | `portfolio_history`, `portfolio_history_rebuild`                                 |
| Persistence platform         | `db/models`, Alembic, schema artefakty, config a shared runtime                  |
| Frontend platform            | `src/app`, `src/modules`, adapters, generated API types a UI                     |
| Experimental engine          | `backend/rust/finance_engine`, bez runtime autority                              |

Každý řádek dostane doménový adresář nebo platformní sekci. Backendový modul
má module card, jen pokud vlastní pravidlo, stav nebo hranici. Pasivní UI,
komponenty a utility zůstávají dohledatelné v generated inventory.

## Průřezové flows

Minimální flow dokumentace:

- browser session → internal token → Python principal;
- manual cash transaction → canonical revision;
- import upload → parse → reconcile → post → publish;
- investment event → canonical state → Holding rebuild;
- provider evidence → price/FX persistence → valuation;
- snapshot refresh → baseline/current value/net worth;
- portfolio/dashboard projection;
- portfolio history invalidation → generation → atomic publication;
- account archive/membership/invitation authorization;
- Alembic migration → schema artifact → parity/drift verification.

## Testovací pokrytí

Každá doména dostane vlastní risk matrix. Centrální test dokumentace pokryje:

- Python unit, service, repository, API, PostgreSQL a migration testy;
- parser fixtures, malformed input, parity a provider transport;
- background job lifecycle, concurrency, retry a recovery;
- finance precision, FX, lineage, snapshots a publication fencing;
- frontend contracts, server adapters, view models a UI interactions;
- architecture boundary a milestone audit testy;
- Rust testy pouze jako experimentální vrstvu, nikoli finance autoritu.

## Generované výstupy

Současné code, API, DB, test a module inventories zůstávají. Doplní se:

- module dependency inventory z importů a allowlistů;
- FastAPI/Next adapter route-to-domain inventory;
- test classification inventory podle markerů, názvů a konfigurace;
- invariant-to-test link checker;
- documentation graph a orphan report;
- metadata/ownership checker;
- kontrola nedotčenosti generated souborů.

Generator poskytuje fakta. Ruční dokumentace vysvětluje jejich význam.
