# 0001 - Use Python Backend

## Decision

Primary backend language is Python with FastAPI.

## Why

- clear modular service structure
- strong ecosystem for APIs, jobs, validation and data workflows
- good fit for orchestration around imports, snapshots and providers

## Consequences

- Next.js must not remain the long-term owner of business logic
- contracts between frontend and backend must become explicit
