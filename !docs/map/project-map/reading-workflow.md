# Reading workflow

Type: reference
Status: current
Owns: minimum-context repository reading sequence
Code: `AGENTS.md`, `.agents/` and documentation indexes
Update when: the required repository reading path changes

1. Read `AGENTS.md` and `memory/codex_rules.md`.
2. For non-trivial work, apply the
   [finance orchestrator](../../../.agents/skills/finance-orchestrator/SKILL.md).
3. Select one project map from this directory.
4. Select one [domain map](../domain-map/README.md).
5. Open the linked domain README and only the relevant invariant, flow, code and
   directly related tests.
6. Load planning only when scope, a durable decision, contract, boundary, or
   high-risk rule is affected.

Use generated inventories for exhaustive discovery. Do not scan the whole
repository when a domain map already identifies the owner.

The primary owns and performs initial routing. Delegated workers receive exact paths
and a curated conversation capsule under
[the context policy](../../../.agents/CONTEXT-POLICY.md); they do not repeat L0/L1
discovery or inherit the complete chat. The primary reassesses routing only after an
explicit `BLOCKED` result, changed scope, or new conflicting authority.
