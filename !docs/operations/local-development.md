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
