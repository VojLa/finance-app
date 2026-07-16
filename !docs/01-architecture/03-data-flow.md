# Data Flow

High-level flow:

1. User imports files or creates manual entries.
2. Parser converts source rows into domain events.
3. Ledger stores investment events and movements.
4. Holdings and snapshots are recalculated.
5. Portfolio/dashboard read models consume snapshots, holdings, prices, and FX rates.

