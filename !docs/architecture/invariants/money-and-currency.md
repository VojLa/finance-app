# Money and currency invariants

Type: invariant
Status: current
Owns: `INV-MONEY-*` and `INV-FX-*`
Code: finance modules, serializers and market evidence readers
Update when: decimal, presentation or FX behavior changes

| ID                 | Exact rule                                                                                                                                                                        | Primary enforcement                                          | Representative evidence                                 |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------- |
| `INV-MONEY-001`    | Financial truth uses `Decimal`, explicit currency and explicit rounding; `float` is never financial truth.                                                                        | shared arithmetic, domain calculations and writers           | snapshot rounding, Holding and public-money tests       |
| `INV-MONEY-002`    | Public money values use the exact fixed-scale decimal string contract.                                                                                                            | Pydantic models and numeric serialization                    | API contract and frontend decimal tests                 |
| `INV-CURRENCY-001` | Account presentation uses `Account.currency`; aggregate portfolio/dashboard/net-worth presentation uses `User.baseCurrency`.                                                      | snapshot/current/net-worth and authorized readers            | account-currency integration and presentation tests     |
| `INV-CURRENCY-002` | Native-currency breakdowns are evidence and cannot replace a scalar aggregate.                                                                                                    | portfolio/dashboard projection and UI models                 | currency-breakdown projection/component tests           |
| `INV-CURRENCY-003` | A provider price quote currency may differ from the acquisition/listing cost currency; valuation preserves both lineages and converts each only through its required direct pair. | market requirements, snapshot projection and history builder | requirements, projection and history-builder tests      |
| `INV-FX-001`       | Historical events use direct event-date FX; snapshot/current valuation uses direct selected market evidence.                                                                      | import reporting FX, market evidence and valuation services  | Raiffeisenbank reporting-FX and snapshot market tests   |
| `INV-FX-002`       | Inverse, cross-rate, stale, future, conflicting and non-representable evidence fails closed.                                                                                      | FX validation and evidence-source policy                     | market-evidence, FX provider and representability tests |

## Snapshot-series semantics

`AccountSnapshot`, `InvestmentAccountSnapshot`, `PortfolioSnapshot` and
`NetWorthSnapshot` are derived read evidence. Their monetary scalars are stored
in the explicit output currency for the account or user view, while each
snapshot retains native-currency breakdowns for cash, investment value, cost
basis, invested/deposited flow and P/L. A user-output scalar never replaces or
discards those native amounts.

Account-filtered snapshot history resolves the published baseline's native
presentation snapshot. Its scalar currency is `Account.currency`, and its
`*ByCurrency` fields retain each original currency independently; only
portfolio, dashboard and net-worth aggregate scalars use `User.baseCurrency`.

Event-date FX is used for invested/deposited flows. Valuation-time price and FX
evidence is separate and is persisted with the snapshot generation. The history
reader uses the exact generation selected by `UserReadModelPublication`; it does
not query live rates or recalculate values in the browser.
