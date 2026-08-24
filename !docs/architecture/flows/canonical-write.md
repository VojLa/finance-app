# Canonical finance write

Type: flow
Status: current
Owns: authorized command to canonical evidence sequence
Code: transactions, investments, canonical state and holdings
Update when: canonical write or lineage changes

Resolve principal → authorize account → validate exact command and idempotency →
write transaction or complete investment event → advance lineage exactly once →
rebuild affected Holding when applicable → commit atomically.
