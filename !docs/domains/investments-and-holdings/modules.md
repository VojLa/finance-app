# Investment and holding modules

Type: module
Status: current
Owns: investment command, lineage and Holding projection runtime layers
Code: `investments/`, `canonical_state/`, `holdings/`, `src/modules/investments/`
Update when: an investment, lineage or Holding layer changes

| Module                    | Responsibility                                                       | Main layers and entry points                                            |
| ------------------------- | -------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `investments`             | validate canonical events and acquire/resolve immutable transfer valuations | API, automatic valuation service, transfer-valuation resolver, repository and public models |
| `canonical_state`         | serialize account lineage and idempotent revision advance            | service and repository                                                  |
| `holdings`                | pure projection plus transactional persistence/rebuild orchestration | API, projection, persistence projection, rebuild service and repository |
| `src/modules/investments` | investment contracts, client and server adapter                      | contract/client, `server/investment-api.ts`                             |

The command path depends on identity, accounts, asset identity and PostgreSQL.
Holdings consume canonical events and feed valuation/read models. Market evidence is
not required to establish event truth. Anycoin transfer valuation evidence is an
append-only overlay over that truth and is never written back into the movement.
Durable Anycoin finalization acquires missing transfer evidence before rebuilding
Holdings; a complete replay reuses persisted evidence without provider I/O.
Exact files are in the
[code inventory](../../map/generated/CODE-INVENTORY.md).
