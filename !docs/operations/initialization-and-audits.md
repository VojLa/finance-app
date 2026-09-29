# Initialization and read-only audits

Type: runbook
Status: current
Owns: safe default seeding and persisted exchange-rate audit
Code: `backend/python/scripts/seed_defaults.py`, `audit_exchange_rates.py`
Update when: seed ownership, reserved identities or exchange-rate audit output changes

## Default seed

From the repository root run `npm.cmd run seed`, or from `backend/python` run:

```powershell
uv run python scripts/seed_defaults.py
```

The seed requires `DATABASE_URL`, takes an advisory transaction lock and is
idempotent for exact reserved categories/rules. It fails rather than overwriting a
conflicting reserved identity. Verify with `test_seed_defaults_integration.py`.

## Exchange-rate audit

From `backend/python`, with a read-only-capable configured database, run:

```powershell
uv run python scripts/audit_exchange_rates.py
```

The command opens a read-only transaction and reports source counts, source
collisions, duplicate identities, invalid rows and legacy snapshot dependencies as
JSON. It never repairs rows. Preserve the report, identify the owning migration or
writer, and do not synthesize replacement FX evidence. Verify its contract with
`test_exchange_rate_audit_script.py`.
