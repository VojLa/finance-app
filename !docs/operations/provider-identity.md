# Provider identity onboarding

Type: runbook
Status: current
Owns: safe operator route for exact provider aliases
Code: `backend/python/scripts/asset_alias.py`, `asset_aliases/`
Update when: provider identity policy changes

List unresolved identities first, then onboard only an exact known provider ID
with expected asset fields. Use `--dry-run` before writing. Never infer identity
from ticker alone, repoint an alias, or place database credentials on the command line.

Run from `backend/python` with `DATABASE_URL` in the environment:

```powershell
uv run python scripts/asset_alias.py list-unresolved --provider twelve_data
uv run python scripts/asset_alias.py onboard --dry-run <exact expected fields>
```

Successful onboarding is create-only and exact replay is harmless. A mismatch,
duplicate, repoint or corrupt row fails closed. After a write, run the focused
asset-alias service/CLI tests and the affected provider requirement check.
