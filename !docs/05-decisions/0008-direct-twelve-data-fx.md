# 0008 Direct Twelve Data FX without pivot or fallback

## Status

Accepted and implemented by R11-J.

## Decision

Twelve Data is the only registered production FX provider. Every conversion
requires one exact persisted direct `FROM/TO` observation from `/time_series`.
The application does not invert, triangulate through CZK, switch provider, or
persist a synthetic pair. Snapshot-time and event-time requirements keep their
separate as-of timestamps.

The API key is required before HTTP and is sent only in the Authorization
header. Quota, transport, schema, direction, freshness, and precision failures
fail the complete refresh without partial persistence.

Historical `cnb` and `yahoo_finance` enum values, rows, and old snapshot lineage
remain readable audit evidence. Source-aware production selection logically
quarantines them from every new calculation. Version 2 pivot roles remain a
read-compatibility contract only.

## Operational gate

Production activation requires both a configured Twelve Data key and confirmed
licensing for the intended internal non-display use. This commercial gate does
not change the deterministic technical contract.
