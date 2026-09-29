# Import and job testing

Type: testing
Status: current
Owns: representative parser, idempotence, job and recovery verification
Code: import, source, background-job and frontend monitor tests
Update when: import/job risks or representative suites change

| Risk                           | Invariant                    | Unit/fixture evidence                           | Integration/E2E evidence                                                                                                              |
| ------------------------------ | ---------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Malformed or unsupported input | `INV-IMPORT-001`             | parser, normalization and source fixture suites | `test_import_parsing_integration.py`                                                                                                  |
| Duplicate canonical posting    | `INV-IMPORT-002`             | deduplication and posting-plan suites           | posting and multifile finalization integration tests; exact-file rejection in the portfolio-history cross-slice disposable acceptance |
| Lease/retry corruption         | `INV-JOB-001`, `INV-JOB-002` | background-job lifecycle and worker tests       | recovery/database and durable-import E2E suites                                                                                       |
| Premature publication          | `INV-PUBLISH-001`            | publication service/executor tests              | `test_r12f_publication_targets_database.py`; Trading212/Anycoin durable-import-to-history cross-slice disposable acceptance           |
| Sensitive payload leak         | `INV-INPUT-001`              | `test_import_upload_security.py`                | public upload/API tests                                                                                                               |

Frontend monitoring is covered by `src/modules/imports/python/import-job-*.test.ts`.
