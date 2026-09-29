# Valuation evidence invariants

Type: invariant
Status: current
Owns: `INV-VALUE-*`
Code: snapshots, baselines, current value, net worth and market-evidence readers
Update when: valuation evidence, cutoff or liability aggregation changes

| ID              | Exact rule                                                                                                                                | Primary enforcement                                | Representative evidence                                    |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- | ---------------------------------------------------------- |
| `INV-VALUE-001` | Current value starts from the newest complete eligible daily baseline and applies only later canonical changes up to server-owned `asOf`. | daily-baseline and current-value services          | daily-baseline cutoff and current-value integration suites |
| `INV-VALUE-002` | Missing, stale, conflicting or non-representable price/FX/cost evidence remains unavailable; no layer invents a value.                    | evidence services, source policy and read models   | market-evidence, unknown-basis and representability tests  |
| `INV-VALUE-003` | Net worth uses persisted asset and liability evidence aligned to the requested identity/cutoff and presentation currency.                 | net-worth evidence/projection/writer services      | liability evidence and net-worth integration suites        |
| `INV-VALUE-004` | Snapshot refresh publishes one internally consistent version after all required evidence succeeds.                                        | refresh plan, executor and publication transaction | snapshot-refresh evidence/final-audit integration tests    |
