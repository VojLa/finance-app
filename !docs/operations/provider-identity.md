# Provider identity onboarding

Type: runbook
Status: current
Owns: safe operator route for exact provider aliases
Code: `backend/python/scripts/asset_alias.py`, `asset_aliases/`
Update when: provider identity policy changes

List unresolved identities first, then onboard only an exact known provider ID
with expected asset fields. Use `--dry-run` before writing. Never infer identity
from ticker alone, repoint an alias, or place database credentials on the command line.
Yahoo onboarding additionally requires the exact `--listing-id`; a Yahoo symbol is
the identity of that listing, not of the whole Asset.

Run from `backend/python` with `DATABASE_URL` in the environment:

```powershell
uv run python scripts/asset_alias.py list-unresolved --provider twelve_data
uv run python scripts/asset_alias.py health-summary --provider twelve_data
uv run python scripts/asset_alias.py onboard --dry-run --actor <operator> <exact expected fields>
```

Example shape for Yahoo (replace every placeholder with reviewed persisted data):

```powershell
uv run python scripts/asset_alias.py onboard --dry-run --actor <operator> --asset-id <asset-id> --listing-id <listing-id> --expected-symbol VWCE --expected-asset-type etf --expected-currency EUR --expected-isin IE00BK5BQT80 --provider yahoo_finance --external-id VWCE.DE
```

Successful onboarding is create-only and exact replay is harmless. A mismatch,
duplicate, repoint or corrupt row fails closed. After a write, run the focused
asset-alias service/CLI tests and the affected provider requirement check.

`create-listing` is the only operator path that creates a new listing and requires
the reviewed Asset identity, exact venue/MIC, native currency, provider identity and
static priority. `reject` records an explicit unresolved decision without changing
any mapping. Onboard, replay, listing creation and rejection append an immutable
`AssetAliasAudit` event; database UPDATE and DELETE are blocked for that audit table.
