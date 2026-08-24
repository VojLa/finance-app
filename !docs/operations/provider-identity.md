# Provider identity onboarding

Type: runbook
Status: current
Owns: safe operator route for exact provider aliases
Code: `backend/python/scripts/asset_alias.py`, `asset_aliases/`
Update when: provider identity policy changes

List unresolved identities first, then onboard only an exact known provider ID
with expected asset fields. Use `--dry-run` before writing. Never infer identity
from ticker alone, repoint an alias, or place database credentials on the command line.
