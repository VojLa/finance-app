# Health and safe diagnostics

Type: runbook
Status: current
Owns: runtime health interpretation and nondisclosing diagnostic path
Code: FastAPI health route, database health, settings, shared logging and Next health adapter
Update when: health endpoints, readiness dependencies or logging controls change

| Signal                        | Meaning                                                        | Does not prove                             |
| ----------------------------- | -------------------------------------------------------------- | ------------------------------------------ |
| `GET /api/v1/health/live`     | Python process and application routing are alive               | database or provider readiness             |
| `GET /api/v1/health/ready`    | required runtime dependencies, including PostgreSQL, are ready | correctness of a specific finance workflow |
| `GET /api/health`             | same-origin compatibility health path                          | independent Next.js business health        |
| request ID and structured log | correlation for one request                                    | permission to log payloads or secrets      |

Check liveness, then readiness, then the affected durable job or domain endpoint.
Use request IDs to correlate safe logs. Never add request bodies, cookies,
authorization headers, financial payloads, database URLs or provider credentials to
diagnostics. Production configuration fails startup when required settings are unsafe.

Escalate when readiness repeatedly fails with a healthy process, a durable job has an
ambiguous lease/owner, or persisted evidence conflicts with the requested identity.
