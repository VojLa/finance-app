# Portfolio and dashboard read models

Type: domain
Status: current
Owns: authorized portfolio, dashboard and browser projection contracts
Code: `portfolio/`, `portfolio_snapshot/`, `dashboard_snapshot/`, browser modules
Update when: projection, presentation or read contract changes

Portfolio and financial dashboard are authorized projections over snapshot, current-value and net-worth evidence. Browser state preserves decimal strings and cannot calculate or recover finance from a legacy response.

## Capabilities and boundaries

- return authorized portfolio summary and persisted snapshot projections;
- aggregate authorized investment accounts (broker, exchange and crypto wallet) in the user's
  base currency for Portfolio, while the dashboard remains an all-account financial overview;
- provide financial dashboard cards, allocation and position contracts;
- keep native-currency breakdowns as explanatory evidence;
- format and display server-owned decimal strings in the browser.

Read models do not accept canonical writes and never calculate missing finance in
Next.js.

`UserReadModelPublication` is the per-user, non-financial publication fence for
Portfolio and Dashboard. Its opaque token is advanced atomically with a published
baseline; the authorized version endpoint returns `204` when the client token is
current. Browser polling is visible-tab-only, ten-minute at most, and keeps only
the token in memory. It never triggers provider I/O or historical validation.

The Python published reader first verifies the current authorized membership set
against this immutable manifest. A mismatch safely makes the projection
unavailable until a complete new publication exists; it never filters accounts
into a partial portfolio. After that check it can use a ten-second, process-local
private cache keyed by user, baseline and requested account scope. The cache has
no public/CDN surface and cannot cross an authorization boundary.

## Navigation

- [Module and layer map](modules.md)
- [Valuation flow](../../architecture/flows/valuation.md)
- [Money/currency and authorization invariants](../../architecture/invariants/README.md)
- [Test matrix](testing.md)
