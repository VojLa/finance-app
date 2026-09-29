# Data and persistence

Type: reference
Status: current
Owns: persistence authority, ownership and migration navigation
Code: `backend/python/app/db/`, `backend/python/migrations/`, `backend/python/database/`
Update when: model ownership, schema process or migration behavior changes

PostgreSQL is the persistence authority. SQLAlchemy is the runtime mapping and Alembic is the sole executable migration owner.

- [Ownership](ownership.md) explains boundaries.
- [Model ownership](model-ownership.md) maps physical model groups to domains.
- [Migrations and recovery](migrations-and-recovery.md) explains safe checks.
- [DB inventory](../map/generated/DB-INVENTORY.md) lists physical facts.
