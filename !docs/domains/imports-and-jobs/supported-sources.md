# Supported import sources

Type: reference
Status: current
Owns: implemented source capabilities
Code: import source registry and fixtures
Update when: a source or supported export shape changes

| Source | Implemented boundary |
| --- | --- |
| Raiffeisenbank | Czech account/card exports to canonical cash transactions |
| Trading212 | supported deposit, buy and dividend investment evidence |
| Anycoin | grouped investment evidence with deterministic anchor/member lineage |
| Manual | supported strict CSV cash rows |

Adding a source requires an enum/registry decision, deterministic fixtures,
normalization, classification, posting semantics and user documentation.
