# Portfolio history

Type: domain
Status: current
Owns: snapshot-series invalidation, rebuild jobs, atomic publication and reads
Code: `portfolio_snapshot/history_reader.py`, `portfolio_history/`, `portfolio_history_rebuild/`
Update when: snapshot rebuild, invalidation, scheduler or publication changes

Portfolio history is a renewable read projection made only from published
snapshots. Canonical transactions and investment events are the immutable audit
source. A backdated import marks the earliest affected time and schedules a
durable rebuild; the replacement snapshot generation becomes visible only after
one atomic publication switch.

## Capabilities and boundaries

- `AccountSnapshot` preserves the complete account state and native currencies.
- `InvestmentAccountSnapshot` contains only the investment branch of an account.
- `PortfolioSnapshot` aggregates authorized investment accounts and positions.
- `NetWorthSnapshot` aggregates complete accounts, including liabilities.
- `SnapshotSeriesHead` and temporal point links publish exact immutable snapshot
  identities across physical generations. Job tables store leases, bounded
  retries, invalidations and capture cursors, but no second financial series.
- Readers join through the exact `UserReadModelPublication` generation and never
  call providers, replay finance or combine generations.
- A failed rebuild leaves the previous complete publication visible.
- On a mixed investment account, exact operational debit/cashback transactions
  change shared cash and net deposited value by the same signed amount. They do
  not change positions, cost basis, fees, taxes or P/L; unsupported pairs remain
  fail-closed.

The public history endpoint serves at most 480 timestamp-unique snapshot points
for the selected range. Portfolio points come directly from `PortfolioSnapshot`;
an account-filtered range uses its published `AccountSnapshot`. Tooltip positions,
allocation, P/L, invested value, investment cost basis and invested cash flow
belong to that same snapshot.
Native `*ByCurrency` values are retained and the scalar output currency is only a
derived presentation aggregate.

Accepted account membership is checked on staging and every read; pending
invitations do not authorize account or portfolio history. Scope changes and
canonical/market changes create durable invalidation evidence. Publication and
empty-scope retirement share a causal watermark, so a delayed older job cannot
restore stale data.

Valuation freshness is the oldest live price or snapshot-FX evidence consumed by
the selected point. Historical event-date FX used for cost or flow metrics does
not make a current valuation look fresher.

## Navigation

- [Module and layer map](modules.md)
- [Publication flow](../../architecture/flows/portfolio-history.md)
- [History invariants](../../architecture/invariants/jobs-and-history.md)
- [Recovery runbook](../../operations/portfolio-history-recovery.md)
- [Test matrix](testing.md)
