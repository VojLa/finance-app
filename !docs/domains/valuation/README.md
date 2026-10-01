# Valuation

Type: domain
Status: current
Owns: snapshots, baselines, current value, net worth and refresh coordination
Code: `snapshots/`, `daily_baselines/`, `current_value/`, `published_snapshot/`, `net_worth/`, `snapshot_refresh/`
Update when: snapshot, baseline, market evidence or refresh behavior changes

Snapshots are immutable derived valuation evidence; canonical transactions, events and liabilities remain business history. Current value is a strict valid baseline plus eligible later canonical changes, not an invented history point.

## Capabilities and boundaries

- calculate and persist account snapshot evidence in account currency;
- allocate non-empty position values at `PERCENTAGE` precision with deterministic
  largest-remainder distribution so the persisted allocation totals exactly 100%;
- freeze daily baselines with canonical lineage;
- publish and read the newest complete minute snapshot set for navigation;
- derive current value from a valid baseline plus eligible later changes;
- persist liability-aware net-worth evidence;
- plan and execute manual or market-backed refresh atomically.

Valuation consumes canonical and market evidence but cannot repair either source.
For a Holding it accepts a price only when listing ID, configured source, exact
provider symbol, native listing currency and freshness all match. Conversion from
that native price currency into account or portfolio currency uses separate direct
FX evidence. A Yahoo price is never persisted pre-converted into portfolio currency.

## Navigation

- [Module and layer map](modules.md)
- [Valuation flow](../../architecture/flows/valuation.md)
- [Money/FX and valuation invariants](../../architecture/invariants/README.md)
- [Test matrix](testing.md)
