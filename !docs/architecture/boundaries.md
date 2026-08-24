# Runtime boundaries

Type: reference
Status: current
Owns: autoritu jednotlivých runtime vrstev
Code: `src/`, `backend/python/app/`, `backend/python/migrations/`
Update when: změní se vlastník dat, auth hranice nebo runtime adaptér

| Boundary | Owns | Must not own |
| --- | --- | --- |
| Next.js UI | presentation and local interaction state | finance calculation, persistence, authorization |
| Next.js adapters | session check, narrow transport validation, internal token forwarding | business rules and financial fallback |
| FastAPI/Python | contracts, principal, authorization, business workflows | browser session UX |
| PostgreSQL | persisted finance evidence | browser-derived totals |
| SQLAlchemy | runtime mapping | executable migration graph |
| Alembic | executable application migrations | application startup migration |
| Rust engine | experimental code | current finance authority |

Python is the final authentication and account-isolation boundary. OpenAPI is
the HTTP source; generated TypeScript transport types are never hand-edited.
