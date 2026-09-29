# Canonical and publication invariants

Type: invariant
Status: current
Owns: `INV-CANON-*`, `INV-IMPORT-*` and `INV-PUBLISH-*`
Code: transactions, investments, imports, jobs, holdings and snapshots
Update when: write atomicity, lineage, idempotence or publication changes

| ID                | Exact rule                                                                                                        | Primary enforcement                                     | Representative evidence                                       |
| ----------------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------- |
| `INV-CANON-001`   | Canonical finance writes are Python-owned and account-authorized.                                                 | transaction/investment services and auth dependencies   | account-access, transaction and manual-investment tests       |
| `INV-CANON-002`   | One successful canonical command advances account lineage exactly once; exact replay does not duplicate evidence. | canonical-state service and writer transaction          | canonical-state, import replay and revision integration tests |
| `INV-CANON-003`   | Holdings, snapshots and read models are derived evidence, never alternate history.                                | projection/rebuild services and TypeScript boundary     | Holding/snapshot projection and frontend boundary tests       |
| `INV-IMPORT-001`  | Untrusted file/provider input is bounded, validated and persisted as explicit issue evidence when unsupported.    | upload/storage, parsers and provider validation         | upload-security, malformed parser and provider parser tests   |
| `INV-IMPORT-002`  | Retry, duplicate file and multi-file execution cannot duplicate canonical finance.                                | deduplication, posting and job executor                 | posting, multifile finalization and durable import E2E tests  |
| `INV-PUBLISH-001` | Incomplete durable work remains hidden behind the last complete baseline or generation.                           | publication queries/services and reader selection       | failed-import fence and history-publication tests             |
| `INV-PUBLISH-002` | Publication moves only complete, internally consistent evidence atomically.                                       | snapshot refresh and generation publication transaction | publication-target and disposable-PostgreSQL tests            |
| `INV-PUBLISH-003` | A durable per-user causal watermark orders publication and empty-scope retirement; delayed older work cannot recreate or replace a newer state. | read-model publication watermark and serializable publisher | snapshot-series PostgreSQL ordering tests                     |
| `INV-PUBLISH-004` | A publication head may reference immutable points from several physical generations; unchanged prefix points retain their exact snapshot identities and are neither copied nor financially replayed. | temporal series heads/links and suffix planner | multi-refresh, suffix-rebuild and prefix-identity tests |

An older import job may finish behind a newer published pointer only when the
current and candidate baselines have the exact same active-account boundary
identity (type, currency, canonical/investment/Holding revisions and selected
liability). Its generation is finalized, while the newer pointer, version and
causal watermark remain unchanged. A retired watermark or any scope/boundary
difference continues to fail closed. Import completion performs this comparison
in a `SERIALIZABLE` transaction against the live authorized account set and the
user's current base currency, so membership and account-state phantoms cannot be
accepted as an equivalent publication.
