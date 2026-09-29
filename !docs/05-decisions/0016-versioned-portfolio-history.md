# 0016 Versioned portfolio history and mandatory backfill

Type: historical
Status: historical
Owns: retained rationale for versioned portfolio-history generations
Code: portfolio history, jobs, scheduler and rebuild modules
Update when: the record is superseded or archived

## Status

Accepted target architecture. Revision `3q0001historygen` implements the
immutable PostgreSQL persistence foundation (generations, publication pointer,
replay checkpoints, evidence lineage, dirty/schedule state and fenced history
jobs). The existing R12 current publication and `NetWorthSnapshot` reader
remain active until the replay, scheduler and public-reader phases pass their
acceptance audit.

## Decision

Portfolio history will become a separate versioned read model rebuilt from
canonical finance and historical market evidence. A late canonical event marks
every affected current member dirty from the event's financial timestamp. A
background rebuild creates a complete private generation and atomically swaps
one user publication pointer only after all account sums, net-worth identities,
canonical manifests and price/FX lineage validate.

Historical generations do not overwrite or compact `AccountSnapshot`,
`NetWorthSnapshot`, `DailySnapshotBaseline`, `ImportJobPublicationTarget` or
R12 `import_event` anchors. Those rows continue to own current-value and import
publication evidence.

History uses a dedicated PostgreSQL `PortfolioHistoryJob` lifecycle for
rebuild, capture, compaction and audit. It follows the fenced lease and retry
principles of the import worker without generalizing the import-specific
`BackgroundJob` schema, payload or completion transaction.

Every private generation records a database-validated build cause. A rebuild
stores the exact dirty epoch and `buildFrom`; capture and compaction store no
dirty epoch and never clear dirty state. Capture is fenced to the exact Prague
bucket close requested by its job. Compaction is fenced to the current parent
publication id and version and its exact input generation/hash. The generation
also stores the SHA-256 of the complete frozen canonical replay input,
including exact listing provider and provider symbol; publication re-freezes
and compares that input before switching the pointer.

The first generation starts at the first canonical financial event. Rebuild is
one chronological replay, not one full replay per point. Yahoo Finance,
CoinGecko and Twelve Data integrations require explicit historical range/batch
ports. Each valuation may use only persisted provider evidence at or before the
point timestamp; future evidence, provider fallback and invented values are
forbidden.

## Time and retention contract

Storage remains naive UTC `TIMESTAMP(3)`, while buckets use `Europe/Prague`.
The nested resolution lattice is:

```text
30m -> 2h -> 6h -> 12h -> 1d -> 2d -> 4d -> 8d -> 16d -> 32d
```

Public ranges select `1D=30m`, `1W=2h`, `1M=6h`, `3M=12h`, `6M=1d`,
`1Y=1d`, `5Y=4d`, `10Y=8d`; `ALL` chooses the finest long-term layer that
keeps at most 480 points.

Detail retention is 24 hours for 30m, 32 days for 2h, 90 days for 6h and 12h,
400 days for 1d, 800 days for 2d, 6 years for 4d and 12 years for 8d.
This matches truthful provider granularity: recent intraday evidence is never
manufactured by repeating a daily close.
Longer 16d/32d layers remain available. Rollups preserve first open, actual
high/low and last close; net worth is never averaged. The persisted point
contract stores `netWorthOpen`, `netWorthHigh`, `netWorthLow` and
`netWorthClose`; the close decomposition is exact (`cash + portfolio -
liabilities = netWorthClose`).

## Local-free historical evidence limits

The anonymous Yahoo chart endpoint is development-only: Yahoo's official
[Developer API catalogue](https://developer.yahoo.com/api/) does not publish a
Finance Chart contract. A credential-free probe on 2026-08-20 observed
`dataGranularity=30m` for `VUAA.MI` and direct `EURCZK=X` requests spanning 1,
8, 30 and 59 days, while 60, 61 and 90 days returned HTTP 422. The adapter
therefore validates exact response identity/granularity, uses only completed
30-minute bars, caps chunks at seven days, observes the empirical 59-day
window, and never performs inverse/pivot/fallback FX. Older evidence remains
daily only for explicitly daily buckets; a provider-determined subdaily request
outside the safe range fails before I/O and cannot silently downgrade. Required
evidence lookback makes the conservative limits about 55 days for listed price
and 51 days for FX; source-capability planning uses a shared conservative
50-day limit. H4 remains the ideal maximum, but H7 truncates local-free 6h/12h
detail at 50 days and covers the older part with `>=1d` points. Canonical Twelve
Data may retain the full 90 days. A `3M` reader may compose older daily and
recent 12h points only while exposing each point's real resolution/coverage; it
must not claim a uniform 12h series. This observed Yahoo behaviour is not
promoted to a production SLA.

CoinGecko officially documents automatic range granularity as 5-minute data
for one day ending at current time, hourly data for another one-day range and
for 2--90 days, and daily data above 90 days. See the
[range endpoint contract](https://docs.coingecko.com/reference/coins-id-market-chart-range).
`provider_determined` therefore preserves 5-minute raw observations for the
rolling 1D layer and hourly raw observations for the 2h/32-day layer; it never
labels hourly or repeated daily data as 30-minute evidence. A keyless
`bitcoin`/`CZK` probe on 2026-08-20 confirmed 287 recent observations over 23h55,
hourly output for historical one-day and current eight-day ranges, and an HTTP
429 after exhausting the shared quota. CoinGecko documents the anonymous pool
as dynamic (~10--30 calls/minute), unsuitable for production polling; 429 and
unexpected cadence fail closed without fallback. See the
[keyless API limits](https://docs.coingecko.com/docs/keyless-public-api).

The implemented historical credential policy has three explicit, non-fallback
modes: public with no key, Demo with `x-cg-demo-api-key` on the configured public
base, and Pro with `x-cg-pro-api-key` on the fixed
`https://pro-api.coingecko.com/api/v3/coins` base. Demo and Pro keys are mutually
exclusive settings. A Pro entitlement or quota failure remains fail-closed; the
server never places either secret in a URL or selects another mode automatically.

## Import and membership behavior

The R12 completion transaction must durably upsert the history dirty range and
enqueue history work for every current member before publishing its existing
anchors and completing. The import does not wait for the long rebuild. Public
status must distinguish current portfolio completion from history rebuilding.

The `3q` rollout seeds invalidation evidence only for roots visible under the
same fail-closed rules as chronological replay. Imported transactions and
investment events require exactly one import-job/batch provenance chain, a
terminal completed or partially completed batch, a completed import workflow,
and a published target for that member. Hidden, queued, failed, ambiguous or
unpublished roots do not create dirty work. Schedules are seeded only for users
with such dirty work, so removed members and empty scopes cannot enter a
permanent retry loop.

The schema currently has no historical membership intervals. MVP generations
therefore apply the user's current accessible active-account set to their whole
history. Membership or account-scope changes force a rebuild from the earliest
affected event. This limitation must be explicit and must not be presented as
membership-as-of reconstruction.

## Implementation warning

The current market planner reads current Holdings and current quote providers;
it cannot be looped over old timestamps. A dedicated as-of replay and
historical provider boundary are mandatory. Documented net-worth snapshot
coverage also rejects bank, cash and savings accounts, so complete
Raiffeisenbank/net-worth history cannot receive PASS until exact as-of support
for those account types exists.
