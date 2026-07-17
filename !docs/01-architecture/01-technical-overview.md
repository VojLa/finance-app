# Technical Overview

Frontend stays in Next.js and TypeScript.

Backend/domain logic is being migrated gradually:

- Python/FastAPI for APIs, orchestration, imports, jobs, and provider integrations.
- Rust for deterministic, performance-heavy calculation engines.
- PostgreSQL remains the database.
- Prisma schema remains the DB model source of truth for now.
