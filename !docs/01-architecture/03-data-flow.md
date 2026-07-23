# Data Flow

## Implemented import flow

```text
register batch -> upload verified bytes -> parse CSV -> persist ImportRow -> normalize row -> detect duplicates
```

1. A writer registers a batch with its source, filename, optional size and
   encoding, and mandatory SHA-256 checksum.
2. The raw body is streamed as `application/octet-stream` to local storage. The
   backend checks its maximum size, declared size, and checksum before publishing
   it atomically.
3. Synchronous parsing reads the verified CSV and persists every physical row,
   including blank or malformed rows, as an `ImportRow`.
4. Normalization maps recognized generic columns to a stable JSON shape. Bad rows
   become `needs_review`; parser failures remain `failed`.
5. Duplicate detection preserves any already imported match and otherwise
   retains the earliest normalized candidate per account, source, and stable
   identity key. All other pending matches become `duplicate`.

The flow is idempotent at batch registration (checksum per user/account) and at
raw storage publication. Parsing and normalization reject a batch that has
already advanced. Normalization and duplicate detection are serialized per
account/source, and every run reconciles matching pending rows across batches.

## Planned, not implemented, continuation

```text
normalized rows -> transactions / investment events -> holdings rebuild -> snapshots -> portfolio and dashboard reads
```

No current Python code posts normalized rows to canonical history, recalculates
holdings, builds snapshots, or exposes a dashboard. Duplicate candidates are
suppressed before posting, but the posting step itself is not implemented. The
portfolio endpoint reads pre-existing `Holding` and
`ExchangeRate` rows directly and reports a warning when FX is missing; it does
not calculate market value or read snapshots.

This distinction is deliberate in the documentation because the planned flow is
a financial correctness boundary, not a description of already-running work.
