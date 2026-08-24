# Valuation

Type: domain
Status: current
Owns: snapshots, baselines, current value, net worth and refresh coordination
Code: `snapshots/`, `daily_baselines/`, `current_value/`, `net_worth/`, `snapshot_refresh/`
Update when: snapshot, baseline, market evidence or refresh behavior changes

Snapshots are immutable derived valuation evidence; canonical transactions, events and liabilities remain business history. Current value is a strict valid baseline plus eligible later canonical changes, not an invented history point.

Verification: [test matrix](testing.md). Rules: [money and currency](../../architecture/invariants/money-and-currency.md).
