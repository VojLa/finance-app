# ADR 0012 - Explicit derived snapshot rounding

Status: Accepted
Date: 2026-08-19
Decision owners: finance-app owner
Supersedes: none
Superseded by: none

## Context

Prices, FX rates, ledger amounts and native quantity evidence use different
physical Decimal scales. Requiring every mathematical product to be exactly
representable at the final snapshot scale makes a valid import fail even though
the evidence itself is exact.

## Decision

Input evidence remains exact: parsers, market writers, canonical ledger and
evidence selectors never round, repair or relabel it. Snapshot arithmetic uses
high-precision Decimal independently of the ambient Decimal context. Only a
derived value crossing a documented output boundary is rounded using
`ROUND_HALF_EVEN`:

- `quantity × price` becomes native `QUANTITY(28,10)`;
- direct FX conversion (including same-currency presentation) becomes output
  `MONEY(18,6)`;
- converted item and aggregate cost basis are `MONEY(18,6)`.

A nonzero result that would round to zero, a non-finite result or a value that
overflows the destination contract fails closed. Derived zero is normalized.
Native portfolio and net-worth `*ByCurrency` breakdowns continue to preserve
`QUANTITY(28,10)` evidence and are therefore not required to equal a rounded
`MONEY(18,6)` scalar merely because their currency matches the output.

This semantic change is represented by coordinated snapshot calculation version 2. Existing version-1 snapshots remain immutable audit evidence; no schema
migration or in-place rewrite occurs.

Coordinated version 3 later retained this rounding contract while adding the
explicit nullable unknown-cost-basis representation. During an active durable
import publication fence only, current-value selection may therefore accept the
literal version set `{2, 3}` so an already complete v2 graph is not hidden by an
unpublishable v3 import. Without a fence only version 3 is accepted. Version 1,
implicit `current - 1` logic, newest-available fallback, and any relaxation of
graph, lineage, market-evidence, or source-policy validation are rejected.
