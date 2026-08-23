## Clean main scenario and frontend CI

R8 adds a release acceptance boundary rather than a new domain module. A
dedicated PostgreSQL 16 database is bootstrapped through the supported
canonical-baseline/Alembic path and proves the active production chain:

`NextAuth browser adapter -> Python accounts/imports -> canonical posting ->
Holdings -> exact alias CLI -> production market providers -> coordinated
snapshots -> portfolio/dashboard/history adapters`.

The representative user base currency is CZK. Raiffeisenbank stays CZK;
Trading212 and Anycoin stay EUR and therefore exercise direct `EUR -> CZK`
Twelve Data evidence. Persisted `User.baseCurrency` remains the target currency
owner, original-currency breakdowns remain unchanged, and any other output
currency requests its own direct pair without inverse or pivot derivation.

The Frontend workflow is a database-free remote gate for generated-contract
drift, Vitest, lint, and TypeScript. The existing Backend Python and Database
Schema workflows remain separate authoritative gates.

Valid dashboard allocation ratios are projected as deterministic exact
four-decimal presentation percentages using largest-remainder distribution.
This presentation step preserves every financial value and guarantees a
`100.0000` total for non-empty allocation sets.
