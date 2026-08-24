# Test strategy

Type: testing
Status: current
Owns: test classification and evidence expectations
Code: Python and TypeScript test roots
Update when: test taxonomy or required risk coverage changes

| Layer | Proves |
| --- | --- |
| Unit/calculation | pure deterministic rules and edge cases |
| Service/repository | domain behavior and persistence boundary |
| HTTP/OpenAPI contract | public route shape and safe errors |
| PostgreSQL/migration | schema, transaction and real infrastructure behavior |
| Parser/provider fixture | normalized input, parity and malformed data handling |
| E2E/recovery | user-visible flow, retry, concurrency and publication recovery |
| Architecture boundary | prohibited legacy path or authority regression |
| Frontend model/UI | adapter contract, presentation state and interaction |

Start focused, then module/domain, integration/contract, static checks and full
gate only when risk requires it. Financial, auth, import, migration and
concurrency work needs a negative or failure-path test.
