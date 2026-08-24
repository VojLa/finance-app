# Investments and holdings

Type: domain
Status: current
Owns: investment events, movements, canonical state and Holding projection
Code: `investments/`, `canonical_state/`, `holdings/`, investment adapters
Update when: investment command, lineage or Holding rebuild changes

An `InvestmentEvent` and its complete movements are canonical history. Account canonical state records committed lineage. Holdings are a derived current projection rebuilt with the canonical transaction and never alternate history.

Verification: [test matrix](testing.md).
