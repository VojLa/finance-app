# ADR 0022 - Unified renewable snapshot projections

Status: Implemented
Date: 2026-09-03
Decision owners: finance-app owner
Supersedes: ADR 0016 for Portfolio graph history

## Decision

`AccountSnapshot`, `InvestmentAccountSnapshot`, `PortfolioSnapshot` and
`NetWorthSnapshot` are the only read projections for Account, Portfolio,
Dashboard and their graphs. Canonical transactions and investment events remain
the immutable audit source; a snapshot is derived data and may be replaced by a
new complete publication after a backdated import.

Every rebuild is staged under one user-neutral snapshot generation and has an
explicit target for every user affected by its account scope. This lets a shared
account use one exact account snapshot while every affected user receives an
independent portfolio/net-worth projection. The existing one-row
`UserReadModelPublication` remains the only public pointer. The publisher
validates the complete target manifest, investment-account snapshots, portfolio
aggregate and net-worth aggregate, then switches all affected user pointers in
one transaction. Readers join through their target pointer and therefore see
either the old complete projection or the new complete projection, never a
partially rebuilt set.

`InvestmentAccountSnapshot` contains investment cash, positions, cost basis,
invested cash flow, P/L, fees, taxes and price/FX evidence. A
`PortfolioSnapshot` aggregates those snapshots by listing and stores the
per-account split. `NetWorthSnapshot` aggregates full account snapshots,
including operational accounts and liabilities. Trading Card rows are
operational transactions: they never change investment events, positions, cost
basis, fees, taxes or P/L. Exact Trading Card debit and cashback rows do share
the broker account's real cash and change `netDeposits` by the same signed
amount under ADR 0020; otherwise the cash-flow difference would appear as a
false investment return. Unknown import rows remain `needs_review` and never
enter either calculation.

Every monetary snapshot metric retains an exact per-currency breakdown in the
original currencies (for example CZK, EUR and USD). The base-currency scalar is
an explicitly derived presentation aggregate and never replaces or discards
the native amounts. The persisted FX evidence identifies every conversion used
to produce that aggregate; event-date cash-flow FX remains distinct from
valuation-time price/FX evidence.

An import that changes canonical data creates a durable rebuild request from
the earliest affected financial timestamp. The worker alone may acquire market
evidence and stages the replacement projection. Normal reads perform neither
provider I/O nor financial replay. Superseded derived snapshot payload is
removed only after a successful pointer switch; canonical/import/price/FX
evidence is never removed by this process.

The Portfolio graph reads the published `PortfolioSnapshot` series directly.
It exposes net worth, investment value and net invested cash; the latter is a
grey dashed series. Tooltip details are taken from the selected snapshot,
including positions, P/L and allocation. Responses carry the publication
identity and valuation timestamp; UI marks values stale after 30 minutes.

An account-filtered graph follows the published baseline's
`presentationSnapshotId` and therefore returns the `AccountSnapshot` in the
account's own main currency, including every preserved `*ByCurrency` native
breakdown. It never substitutes the user's base-currency companion snapshot.
Historical `PortfolioSnapshotInput` rows intentionally do not hold a foreign
key to the live `AccountMember` row: membership is enforced while staging and
on every read, while later revocation must remain possible without deleting or
rewriting historical evidence.

Publication and empty-scope retirement share a durable per-user causal
watermark. Removing the public pointer therefore leaves a tombstone which
rejects any delayed older job; a later rebuild may publish only with a strictly
newer causal job timestamp. The watermark carries no monetary values.

## Consequences

- Revisions `3y0001snapshotjobs` and `3z0001historydrop` complete the cutover:
  durable rebuild/capture state now uses `SnapshotSeries*`, and all fourteen
  `PortfolioHistory*` tables plus their five enums are removed.
- The physical generation is a publication safety mechanism, not a second
  financial-history model and not a public graph source.
- A failed rebuild retains the last valid published state.
- Snapshot schema changes require SQLAlchemy/Alembic parity, migration preflight
  evidence and pointer-gated authorization tests.
