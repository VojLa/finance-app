# 0008 Direct Twelve Data FX without pivot or fallback

Type: historical
Status: historical
Owns: retained rationale for direct FX evidence
Code: FX providers, market evidence and valuation
Update when: the record is superseded or archived

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

## Local-free addendum (2026-08-19)

`MARKET_EVIDENCE_SOURCE_MODE=local_free` is a deliberately temporary,
development/test-only evidence policy for fixture verification. It is rejected
when `ENVIRONMENT=production`. In that mode Yahoo Finance is the recorded
source for non-crypto listed prices and direct `FROMTO=X` FX pairs; crypto
prices remain CoinGecko. Yahoo is not a licensed production substitute and is
never relabelled as Twelve Data, a broker, or an exchange.

This endpoint is not treated as an approved production market-data API. Before
any non-local automated collection, the operator must obtain and document
Yahoo's applicable permission/licence and re-evaluate its terms of use. The
local-free mode must be removed (or replaced by a licensed provider and a
separate accepted decision) before production activation.

An operator onboards one exact ticker per non-crypto asset (for the Trading212
fixture, `VUAA.MI` in EUR). The policy picks a source by asset type, not by
availability: crypto → CoinGecko; all other investment assets → Yahoo. Missing
or ambiguous aliases fail the refresh. The adapter accepts only the requested
chart symbol, returned quote currency, timestamped close and direct pair; it
does not use an inverse, pivot, cross-listed symbol, or runtime fallback.

Yahoo direct FX provider calls are batched by one exact pair so historical
requirements share one bounded daily chart response. Every requested date must
still receive exactly one validated non-future observation before the atomic
writer is entered.
