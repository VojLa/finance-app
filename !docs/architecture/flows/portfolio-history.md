# Portfolio history publication

Type: flow
Status: current
Owns: snapshot-series rebuild, staged validation and atomic user publication
Code: snapshot rebuild/worker and portfolio history readers
Update when: snapshot generation, rebuild, capture or publication changes

Portfolio history is the published series of immutable read-model snapshots. An
import that changes canonical history creates a durable rebuild request from the
earliest affected financial timestamp. The worker replays canonical data and
materializes a complete snapshot generation containing `AccountSnapshot`,
`InvestmentAccountSnapshot`, `PortfolioSnapshot` and `NetWorthSnapshot` rows.

The staged generation has an exact target manifest for every affected user. The
publisher validates the manifest and all snapshot relationships, then switches
the corresponding `UserReadModelPublication` pointers in one transaction. A
reader joins only through that exact current publication generation, so it sees
the previous complete series or the new complete series, never a partial mix.

Current snapshot capture is a separate workflow; it does not substitute for a
backdated rebuild. Provider I/O and replay are limited to the builder/worker.
Normal history reads perform no provider calls, replay, or financial
recalculation.

The public portfolio/history API returns the selected generation's persisted
snapshot points and their valuation timestamps. Account, investment, portfolio,
and net-worth values are read from that generation using the user's output
currency, while native-currency breakdowns remain available as evidence. A
failed or incomplete rebuild leaves the last complete publication visible.

Durable rebuild/capture orchestration is stored in `SnapshotSeries*` tables.
Revision `3y0001snapshotjobs` migrates pending rebuild/capture work and revision
`3z0001historydrop` removes the former generation, point, coverage, audit,
compaction and cleanup persistence after fail-closed preflight checks.
