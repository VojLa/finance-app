# Cross-domain flows

Type: reference
Status: current
Owns: navigation for workflows crossing domain boundaries
Code: services, workers and adapters
Update when: a cross-domain sequence or handoff changes

| Flow                                        | Boundary                                               |
| ------------------------------------------- | ------------------------------------------------------ |
| [Identity bridge](identity-bridge.md)       | browser session to Python principal                    |
| [Canonical write](canonical-write.md)       | command to committed canonical evidence                |
| [Import publication](import-publication.md) | untrusted file to durable published result             |
| [Market evidence](market-evidence.md)       | exact provider identity to persisted price/FX evidence |
| [Valuation](valuation.md)                   | canonical and market evidence to read models           |
| [Portfolio history](portfolio-history.md)   | invalidation to immutable publication                  |
