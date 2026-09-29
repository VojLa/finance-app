## Strict current-value projection

Type: historical
Status: historical
Owns: milestone evidence for strict current-value projection
Code: current-value projection at the recorded milestone
Update when: evidence is archived or replaced by a newer record

R10-D2 makes current portfolio and dashboard finance an ephemeral Python read
model. The authenticated browser adapters call `/api/v1/portfolio/current` and
`/api/v1/dashboard/current`; they no longer create a minute snapshot graph.
Both endpoints use the same `current_value` application service and one
server-owned, minute-aligned `asOf`.

The service selects the newest D1 baseline, revalidates its exact manifest and
canonical cutoffs under `REPEATABLE READ READ ONLY`, reconstructs only canonical
forward roots, and derives trusted market requirements from the reconstructed
open listings. Provider I/O and atomic market evidence writes occur after the
planning transaction is closed. A second stable read transaction revalidates
the exact baseline, changes, account configuration, and market plan before any
financial response is produced.

Cash uses baseline native balances plus forward Transactions. Investments use
baseline AccountSnapshot items plus forward InvestmentEvents/Movements through
the shared Holding movement projector; current Holding is not a quantity or cost
basis source. Liabilities are replacement observations. Historical metrics add
event-date converted forward evidence to persisted baseline scalars; current
cash, liabilities, market value, and unrealized P/L use current-as-of evidence.
The reconstructed state is projected once into User.baseCurrency and, for
account presentation, Account.currency. Dashboard is a pure projection of the
same current portfolio result.

No baseline, a newest-invalid baseline, changed lineage, or incomplete market
evidence produces the safe unavailable contract. There is no older-baseline,
full-history, Holding, Prisma, legacy, or browser arithmetic fallback. Persisted
daily snapshot creation remains the baseline machinery; persisted NetWorth
history remains unchanged and receives no synthetic current point.
