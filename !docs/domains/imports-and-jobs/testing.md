# Import and job testing

| Risk | Layer | Evidence |
| --- | --- | --- |
| Malformed input | parser fixture | `test_import_*`, source fixture suites |
| Duplicate posting | PostgreSQL integration | deduplication and posting tests |
| Retry/publication failure | E2E/recovery | background job and durable executor tests |
| Sensitive-data leak | contract/security | upload security and safe error tests |
