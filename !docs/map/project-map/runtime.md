# Runtime map

Type: reference
Status: current
Owns: runtime processes, trust boundaries and authority
Code: `src/`, `backend/python/app/`, PostgreSQL and provider adapters
Update when: a runtime process or authority boundary changes

```text
Browser → Next.js UI/adapters → FastAPI /api/v1 → PostgreSQL
                                      │
                         SQLAlchemy + Alembic
```

| Layer           | Authority                                      |
| --------------- | ---------------------------------------------- |
| UI              | presentation and interaction state only        |
| Next.js adapter | session bridge and transport validation        |
| Python          | contracts, authorization and finance workflows |
| PostgreSQL      | persisted application evidence                 |
| SQLAlchemy      | runtime schema mapping                         |
| Alembic         | executable migrations                          |
| Rust            | experiment without runtime authority           |
