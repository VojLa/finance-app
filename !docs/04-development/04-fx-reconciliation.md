# FX reconciliation and recovery

R11-J does not delete historical CNB or Yahoo evidence. New calculations select
only `ExchangeRateSource.twelve_data`, which logically quarantines legacy rows.

## Read-only audit

Run from `backend/python` with `DATABASE_URL` configured:

```powershell
uv run python scripts/audit_exchange_rates.py
```

The JSON report includes counts per source, same-pair/date source collisions,
duplicate physical source identities, invalid rows, and AccountSnapshot or
NetWorthSnapshot records that reference a legacy rate ID. The command opens a
read-only transaction and performs no repair.

## Backup before any operator cleanup

No cleanup is part of normal application startup. Before a separately approved
operator change, take a consistent PostgreSQL backup of at least
`ExchangeRate`, `AccountSnapshot`, `AccountSnapshotItem`, and
`NetWorthSnapshot`; record the Alembic revision and audit report beside it.
Prefer a complete custom-format database backup when practical.

Verify restoration into a separate database, run `database_migrate.py check`,
and rerun the audit before touching the source database. Rollback is restoration
of that verified backup, not reconstruction of deleted rows.

## Reconciliation policy

- Never rewrite an immutable historical snapshot to point at a new provider.
- Never relabel a CNB or Yahoo row as Twelve Data.
- Create direct Twelve Data evidence through the normal market refresh.
- Generate a newer snapshot through the normal authenticated refresh workflow.
- Delete legacy evidence only under a separately reviewed retention decision and
  only when the audit proves that no snapshot references it.
