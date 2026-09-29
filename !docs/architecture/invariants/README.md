# Invariant catalog

Type: reference
Status: current
Owns: exact cross-domain technical and financial invariants
Code: Python services, persistence and browser adapters
Update when: invariant, enforcement point or test evidence changes

| Family                                                    | Scope                                           |
| --------------------------------------------------------- | ----------------------------------------------- |
| [Money and currency](money-and-currency.md)               | decimal contracts, presentation and FX          |
| [Canonical and publication](canonical-and-publication.md) | lineage, idempotence, jobs and derived evidence |
| [Security and isolation](security-and-isolation.md)       | identity, authorization and sensitive data      |
| [Valuation evidence](valuation-evidence.md)               | baseline, evidence selection and net worth      |
| [Jobs and portfolio history](jobs-and-history.md)         | leases, invalidation, generation and replay     |

Each invariant has one exact statement, its primary enforcement point and
representative test evidence. Domain matrices may reference the ID but must not
redefine the rule.
