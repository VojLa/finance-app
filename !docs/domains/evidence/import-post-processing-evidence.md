## Import post-processing outcome

`ImportBatchPostingService` now returns an internal immutable terminal result
that includes counts of imported Transaction and InvestmentEvent targets. Each
imported row must reference exactly one target and target counts must equal
`rowsImported`. These counts are orchestration evidence and are not public API
fields.

After that service commits, 5K-E2 may rebuild Holdings for an investment-event
batch and then invokes R5-B3A for all snapshots reachable by the principal's
current user. Market evidence always precedes snapshot execution. The exact
command uses source `import_event`, the common AccountSnapshot/NetWorth
calculation version, and one minute bucket derived from persisted
`ImportBatch.completedAt` for snapshot, calculation, and creation time.
Replaying the batch therefore reuses the same Holding, market, and snapshot
identities without a current-time replacement.

These stages are not one atomic transaction. Market failure leaves posting and
rebuilt Holdings committed and prevents snapshot execution. Snapshot failure
after a market commit leaves valid append-only evidence intact. Empty market
requirements are valid. Missing or ambiguous aliases are generically
unavailable before HTTP, and the import boundary never derives aliases from
ticker, ISIN, or name. A delayed replay rejects provider observations newer
than its original bucket rather than repairing timestamps; the manual refresh
endpoint owns later current-state recovery. Alias onboarding is outside
R5-B3C.

`ImportPostResponse.snapshot_refresh_status` is a Python/API-only enum with
`created`, `replayed`, `not_required`, `unavailable`, and `conflict`. It does
not alter ImportBatch status and has no database enum. Its fields and OpenAPI
shape remain unchanged, and neither it nor the deterministic generic ImportLog
exposes market IDs, provider metadata, requirements, or counts. Known
post-processing failure leaves canonical imported rows and any committed
Holding, market evidence, or AccountSnapshot rows intact. ImportLog records
audits, not job progress. There is no compensation, migration, job table,
scheduler, worker, queue, or background task.

## Final coordinated-refresh audit

The completed 5K audit confirms the end-to-end persisted coverage, valuation,
physical projection, writer, lineage, manual-entry, and import-entry
contracts. Physical AccountSnapshot identity remains
`(accountId, timestamp, output currency, granularity)` and NetWorthSnapshot
identity remains `(userId, timestamp, currency, granularity)`. The same minute
reached through manual and import orchestration never creates an alternate
timestamp: exact metadata replays, while different immutable source or
recalculation metadata conflicts without update, delete, or repair.

Role-mixed coverage still writes owner/admin/editor targets, reuses viewer
targets only from exact persisted evidence, and sends the complete ordered
lineage to the final SERIALIZABLE NetWorth guard. Partial account-stage
commits remain replayable after a later failure. E1 reports state/conflict as
generic HTTP 409; E2 preserves the committed import and reports the same known
outcomes as HTTP 200 `snapshot_refresh_status`. Neither response exposes
account/source lineage, FX evidence, financial breakdowns, or internal
exceptions.

The physical PostgreSQL catalog retains naive `TIMESTAMP(3)`, canonical
numeric scales, JSONB audits, existing foreign-key delete behavior, and
currency-sensitive unique indexes. No 5K migration, job-state table,
scheduler, worker, queue, background task, compensation path, or support for
bank/cash/savings AccountSnapshots was introduced.
