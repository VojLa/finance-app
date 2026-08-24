# Money and currency invariants

Type: invariant
Status: current
Owns: `INV-MONEY-*` and `INV-FX-*`
Code: finance modules, serializers and market evidence readers
Update when: decimal, presentation or FX behavior changes

- `INV-MONEY-001`: Financial truth uses `Decimal`, explicit currency and explicit rounding; `float` is never financial truth.
- `INV-MONEY-002`: Public money values use the exact fixed-scale decimal wire contract.
- `INV-CURRENCY-001`: Account primary presentation is `Account.currency`; aggregate portfolio/dashboard/net-worth presentation is `User.baseCurrency`.
- `INV-CURRENCY-002`: Native-currency breakdowns are evidence and cannot replace a scalar aggregate.
- `INV-FX-001`: Historical events use direct event-date FX; snapshot/current valuation uses direct selected market evidence.
- `INV-FX-002`: Inverse, cross-rate, stale, future, conflicting and non-representable evidence fails closed.
