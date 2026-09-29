# ADR 0019 - Navigation reads published snapshots

Status: Accepted
Date: 2026-08-31
Decision owners: finance-app owner
Supersedes: none
Superseded by: none

## Context

Portfolio and Dashboard used the ephemeral `current_value` endpoints during
navigation. That path can acquire live price and FX evidence and therefore made
ordinary page loads wait for external providers. The product decision is that
scheduled snapshot refresh is the only source of new market evidence for these
surfaces.

## Decision

Each successful minute `manual_recalculation` snapshot refresh publishes the
same complete `DailySnapshotBaseline` graph as its immutable account and
net-worth snapshots. `POST /api/v1/portfolio/published` and
`POST /api/v1/dashboard/published` select the newest valid published baseline
for the authenticated user and perform only authorized exact snapshot reads.
They never invoke `CurrentValueService`, a market provider, FX acquisition, or
snapshot refresh.

The existing `/current` endpoints remain the explicit ephemeral valuation path;
they are not called by browser navigation.

## Consequences

- Navigation shows the most recently published snapshot timestamp, rather than
  an on-demand live value.
- An incomplete or invalid publication fails closed; readers do not select a
  partial account set or invent a replacement value.
- No schema change is required: the existing baseline/account lineage stores
  the immutable selector set.
