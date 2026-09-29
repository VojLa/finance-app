# Investments and holdings map

Type: domain-map
Status: current
Owns: L1 routing for investments and Holdings
Code: investment, canonical-state, Holding and browser investment modules
Update when: investment/Holding ownership, entry point or dependency changes

ID: `DOM-INVEST`
Purpose: canonical investment history, lineage and current Holding projection
Source of truth: investment events with complete movement sets

- Entry points: manual investment API and imported posting writer.
- Modules: `investments/`, `canonical_state/`, `holdings/`.
- Depends on: identity, accounts and asset identity.
- Used by: valuation, portfolio and history.
- Tests: [domain test matrix](../../domains/investments-and-holdings/testing.md).
- Details: [domain README](../../domains/investments-and-holdings/README.md) and [modules](../../domains/investments-and-holdings/modules.md).
