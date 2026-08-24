# Canonical and publication invariants

Type: invariant
Status: current
Owns: `INV-CANON-*`, `INV-IMPORT-*` and `INV-PUBLISH-*`
Code: transactions, investments, imports, jobs, holdings and snapshots
Update when: write atomicity, lineage, idempotence or publication changes

- `INV-CANON-001`: Canonical finance writes are Python-owned and account-authorized.
- `INV-CANON-002`: One successful canonical command advances account lineage exactly once; exact replay does not duplicate evidence.
- `INV-CANON-003`: Holdings and snapshots are derived evidence, not alternate history.
- `INV-IMPORT-001`: Untrusted file/provider input is bounded, validated and persisted as explicit issue evidence when unsupported.
- `INV-IMPORT-002`: Retry, duplicate file and multi-file execution cannot duplicate canonical finance.
- `INV-PUBLISH-001`: Incomplete durable work remains hidden behind the last complete baseline.
- `INV-PUBLISH-002`: Publication moves only complete, internally consistent evidence atomically.
