# Import and job modules

Type: module
Status: current
Owns: import pipeline, source adapters and durable-job runtime layers
Code: `backend/python/app/modules/imports/`, `backend/python/app/modules/jobs/`, `src/modules/imports/`
Update when: a parser stage, source adapter, job layer or dependency changes

| Area              | Responsibility                                       | Main layers and entry points                                                |
| ----------------- | ---------------------------------------------------- | --------------------------------------------------------------------------- |
| import intake     | bounded storage and persisted batch/row/issue state  | `api.py`, `service.py`, `repository.py`, `storage.py`, `models.py`          |
| transformation    | parse, normalize, deduplicate and classify           | parsers, normalizers, classification and deduplication modules              |
| source adapters   | Anycoin, Trading 212 and Raiffeisenbank contracts    | source files plus reconciliation/reporting-FX modules                       |
| canonical posting | transaction/investment plans and post-processing     | posting services, asset resolution, multi-file and post-processing services |
| durable jobs      | lifecycle, leases, worker, retry and publication     | jobs API, service/repository, worker, executor and publication modules      |
| frontend adapters | upload, status events, monitor and retry UI contract | `src/modules/imports/python/`                                               |

Imports depend on identity, accounts, canonical transaction/investment writers,
market identity and snapshot refresh. Jobs coordinate those owners but do not duplicate
their business rules. Exact files are in the [code inventory](../../map/generated/CODE-INVENTORY.md).
