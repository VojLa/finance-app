# Test strategy

Type: testing
Status: current
Owns: test classification and evidence expectations
Code: Python and TypeScript test roots
Update when: test taxonomy or required risk coverage changes

| Layer                   | Proves                                                         |
| ----------------------- | -------------------------------------------------------------- |
| Unit/calculation        | pure deterministic rules and edge cases                        |
| Service/repository      | domain behavior and persistence boundary                       |
| HTTP/OpenAPI contract   | public route shape and safe errors                             |
| PostgreSQL/migration    | schema, transaction and real infrastructure behavior           |
| Parser/provider fixture | normalized input, parity and malformed data handling           |
| E2E/recovery            | user-visible flow, retry, concurrency and publication recovery |
| Architecture boundary   | prohibited legacy path or authority regression                 |
| Frontend model/UI       | adapter contract, presentation state and interaction           |

## Selection and prerequisites

Use the narrowest layer that proves the changed behavior:

1. focused unit or contract test;
2. owning module/domain tests;
3. PostgreSQL integration, migration, provider-contract or cross-domain tests;
4. static/type/boundary checks;
5. full quality gate only at a release, broad refactor or final integration boundary.

Database tests require an isolated PostgreSQL `DATABASE_URL`. Migration and disposable
PostgreSQL suites own their schema lifecycle and must never target a shared database.
Provider tests use bounded fixtures or mocked transports unless a test explicitly owns
external integration. Financial, auth, import, migration and concurrency work needs a
negative or failure-path test.

After a blocker fix, rerun the failing evidence, changed module tests and immediately
connected integration boundary. Do not repeat a full audit unless the scope changed.
