# Supported import sources

Type: reference
Status: current
Owns: implemented source capabilities
Code: import source registry and fixtures
Update when: a source or supported export shape changes

| Source         | Implemented boundary                                                 |
| -------------- | -------------------------------------------------------------------- |
| Raiffeisenbank | Czech account/card exports to canonical cash transactions            |
| Trading212     | deposit, buy and dividend evidence; exact ISIN/ticker/currency market-alias onboarding for the accepted fixture set |
| Anycoin        | grouped investment evidence with deterministic anchor/member lineage |
| Manual         | supported strict CSV cash rows                                       |

Adding a source requires an enum/registry decision, deterministic fixtures,
normalization, classification, posting semantics and user documentation.

Trading 212 provider aliases are created only after successful canonical
posting. The implemented fixture identities are fail-closed: an unknown or
conflicting ISIN/ticker/currency combination stops financial finalization and
must be reviewed instead of being guessed from the ticker alone.
Yahoo aliases created by Trading 212 or Anycoin finalization are scoped to the exact
posted listing. CoinGecko and existing Twelve Data onboarding retain their current
compatible asset-level contract in this stage.
