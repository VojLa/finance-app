# Runtime map

```text
Browser → Next.js UI/adapters → FastAPI /api/v1 → PostgreSQL
                                      │
                         SQLAlchemy + Alembic
```

| Layer | Authority |
| --- | --- |
| UI | presentation and interaction state only |
| Next.js adapter | session bridge and transport validation |
| Python | contracts, authorization and finance workflows |
| PostgreSQL | persisted application evidence |
| SQLAlchemy | runtime schema mapping |
| Alembic | executable migrations |
| Rust | experiment without runtime authority |
