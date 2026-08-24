# Portfolio-history publication

Type: flow
Status: current
Owns: invalidation to selected immutable history generation
Code: portfolio history and rebuild modules
Update when: invalidation, build, scheduling or publication changes

Canonical invalidation → durable job → deterministic lattice/build → evidence
validation → immutable generation → atomic publication selection. Readers see
the previous complete generation until the replacement is complete.
