# Local development

Type: runbook
Status: current
Owns: supported local startup and verification entry points
Code: root README, `backend/python/README.md`, Docker Compose
Update when: runtime command or prerequisite changes

Use `docker compose up --build` for the full stack, or run Next.js and FastAPI
separately according to the root and backend READMEs. Python requires `uv` and
PostgreSQL for data-backed endpoints. Run focused checks first, then
[quality gates](../testing/quality-gates.md). Do not run production build while
`next dev` owns `.next`.

Use `/api/v1/health/live` to verify the Python process and
`/api/v1/health/ready` to verify PostgreSQL and, when enabled, both portfolio-history
runtime tasks. Docker Compose deliberately leaves that runtime disabled until the
local database has been migrated through revision 3r. The Next.js `/api/health`
route is a compatibility adapter, not a separate health authority. Environment and
safe diagnostic behavior are documented in [health and diagnostics](health-and-diagnostics.md).
