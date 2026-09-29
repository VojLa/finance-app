## Exact portfolio currency breakdowns

Type: historical
Status: historical
Owns: milestone evidence for portfolio currency breakdowns
Code: portfolio projection at the recorded milestone
Update when: evidence is archived or replaced by a newer record

R6-A extends only the `portfolio_snapshot` presentation boundary. The physical
AccountSnapshot `cashValueByCurrency` and `netDepositsByCurrency` JSONB columns
already existed and remain owned by the snapshot persistence writer. The exact
reader decodes them as canonical `MONEY NUMERIC(18,6)` strings, rejects absent
or malformed evidence, and emits immutable currency/amount tuples sorted by
currency. It never queries Transactions or Holdings, reconstructs a breakdown
from a scalar, inserts an output-currency default, or reads live FX.

The pure projection revalidates tuple type, currency identity, ordering,
uniqueness, MONEY precision, and the coherence rules that can be proven without
inventing another valuation algorithm. An empty breakdown requires a zero
scalar; a breakdown containing only the output currency must equal its scalar.
For multi-currency net deposits, the physical audit stores only historical rate
identities rather than the full rate values, so independent scalar
recalculation is not safe. The AccountSnapshot writer therefore retains
ownership of that financial relationship while R6-A verifies canonical
breakdown evidence exactly.

Multi-account aggregation sums entries only within the same original currency
using Decimal arithmetic and preserves currencies that cancel to zero. It
sorts the unique result by currency and performs no FX conversion or rate
lookup. Single-account summaries, account summaries nested in the
multi-account response, and the aggregate summary expose required
`cashByCurrency` and `netDepositsByCurrency` arrays. The dashboard contract is
unchanged. R6-B owns rendering these fields in the portfolio UI; R6-A adds no
visual frontend, schema, migration, or snapshot calculation change.

R6-B consumes those fields only in the portfolio presentation. Scalar
`cashValue` and `netDepositsValue` cards remain denominated in the selected
view's output currency. Two semantic currency/value panels display
`cashByCurrency` and `netDepositsByCurrency` as original-currency evidence.
They preserve server order and exact Decimal strings, including negative and
zero entries, and render explicit messages for empty arrays.

The `Vše` view uses the server aggregate summary, while an account selection
uses that account's server summary by reference. The switch is local state over
the already loaded response and makes no request. The component performs no
sorting, reduction, account aggregation, FX, scalar/breakdown reconstruction,
legacy read, or history substitution. Dashboard presentation, OpenAPI,
generated TypeScript, backend code, schema, and migrations remain unchanged.
The later R6 final audit passed; R7-A leaves this presentation contract unchanged.
