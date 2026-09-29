# Historical record — Step 3E-B Alembic ownership cutover

This is a point-in-time audit instruction retained for historical evidence. It
is not current Codex guidance and must not be used to direct implementation,
migration, branch, or Prisma-client decisions. Current authority is
`AGENTS.md`, `memory/codex_rules.md`, `!docs/`, and `!planning/`.

# CODEX TASK – STEP 3E-B FINAL LOCAL AUDIT AND BRANCH SYNCHRONIZATION

## Repository

```text
VojLa/finance-app
```

## Pull requests

### Dependency PR

```text
PR #13
Title: build(db): prepare Alembic ownership cutover
Branch: build/alembic-cutover-preparation-clean
Base: main
Expected current HEAD: 38fa8d79ea8fed62f28d7a588a1e21e4765ccd56
Expected state: open
```

### Target PR

```text
PR #15
Title: build(db): transfer migration ownership to Alembic
Branch: build/alembic-ownership-cutover
Base: build/alembic-cutover-preparation-clean
Expected starting HEAD: 8eddb3c517aa37016073dc677e85958eb20a1898
Expected state: open
```

## Objective

Synchronize Step 3E-B with the latest Step 3E-A branch and perform a complete local audit.

Step 3E-B must prove that:

```text
Alembic:
  is the sole migration owner
  owns all future schema changes
  has head revision 3e0001cutover

Prisma migrations:
  remain a frozen historical archive
  cannot be used for regular deployment

Prisma Client:
  remains available as a runtime compatibility client

Remote databases:
  do not currently exist
  no fake staging or production receipts are created

Business database schema:
  remains physically unchanged
```

Do not merge PR #13 or PR #15.

---

# 1. Inspect the current remote state

From the repository root:

```powershell
git fetch origin --prune

gh pr view 13 --json number,state,isDraft,mergeable,baseRefName,headRefName,headRefOid
gh pr view 15 --json number,state,isDraft,mergeable,baseRefName,headRefName,headRefOid
```

Record the real current values.

Expected initial state:

```text
PR #13:
  state = OPEN
  base = main
  head = build/alembic-cutover-preparation-clean
  expected head = 38fa8d79ea8fed62f28d7a588a1e21e4765ccd56

PR #15:
  state = OPEN
  base = build/alembic-cutover-preparation-clean
  head = build/alembic-ownership-cutover
  expected head = 8eddb3c517aa37016073dc677e85958eb20a1898
```

If either remote head has advanced, use the latest remote state and record the difference in the final report.

Do not rely only on the expected SHAs.

---

# 2. Prepare the 3E-B branch

```powershell
git switch build/alembic-ownership-cutover
git pull --ff-only origin build/alembic-ownership-cutover
git status --short
git rev-parse HEAD
```

The working tree must be clean.

Do not discard uncommitted user work.

If unrelated local changes exist, stop and report them rather than deleting or overwriting them.

---

# 3. Synchronize Step 3E-B with current Step 3E-A

PR #15 was originally based on an older Step 3E-A head. Synchronize it with the current remote dependency branch.

Use a normal merge commit. Do not rewrite the published PR history.

```powershell
git merge --no-ff origin/build/alembic-cutover-preparation-clean `
  -m "merge: sync latest 3E-A preparation"
```

Expected result:

- no force push,
- no rebase of the published branch,
- the latest Step 3E-A tests and fixes are retained,
- all Step 3E-B ownership changes remain present.

Do not resolve conflicts globally using:

```text
git checkout --ours .
git checkout --theirs .
git merge -X ours
git merge -X theirs
```

If a conflict occurs, inspect it file by file.

The resolution must preserve both:

1. the latest verified Step 3E-A behavior,
2. the intended Step 3E-B completed-cutover behavior.

After synchronization:

```powershell
git merge-base --is-ancestor `
  origin/build/alembic-cutover-preparation-clean HEAD

git status --short
git log --oneline --decorate -5
```

The ancestry command must return exit code `0`.

Push the synchronization commit:

```powershell
git push origin build/alembic-ownership-cutover
```

Do not force push.

---

# 4. Verify the Step 3E-B-only diff

Compare against the latest Step 3E-A branch:

```powershell
git diff --stat origin/build/alembic-cutover-preparation-clean...HEAD
git diff --name-status origin/build/alembic-cutover-preparation-clean...HEAD
```

Expected Step 3E-B files:

```text
.github/workflows/database-schema.yml
backend/python/app/db/README.md
backend/python/database/README.md
backend/python/database/cutover/README.md
backend/python/database/cutover/environments.toml
backend/python/database/schema_ownership.toml
backend/python/migrations/README.md
backend/python/migrations/versions/3e0001cutover_alembic_ownership.py
backend/python/scripts/alembic_baseline.py
backend/python/scripts/database_migrate.py
backend/python/scripts/migration_policy.py
backend/python/tests/test_alembic_baseline.py
backend/python/tests/test_alembic_configuration.py
backend/python/tests/test_alembic_integration.py
backend/python/tests/test_database_migrate.py
backend/python/tests/test_database_schema.py
backend/python/tests/test_migration_policy.py
package.json
scripts/prisma-archive-verify.mjs
```

Small additional changes are allowed only when they are direct fixes required by the audit.

There must be no temporary diagnostic files or workflows.

Forbidden examples:

```text
.github/workflows/format-*.yml
.github/workflows/diagnose-*.yml
backend/python/*report*.txt
backend/python/*diagnostic*.txt
```

---

# 5. Scope verification

Confirm that Step 3E-B does not alter the physical business schema.

```powershell
git diff --exit-code `
  origin/build/alembic-cutover-preparation-clean...HEAD `
  -- prisma/schema.prisma

git diff --exit-code `
  origin/build/alembic-cutover-preparation-clean...HEAD `
  -- prisma/migrations

git diff --exit-code `
  origin/build/alembic-cutover-preparation-clean...HEAD `
  -- backend/python/database/baseline/schema.sql

git diff --exit-code `
  origin/build/alembic-cutover-preparation-clean...HEAD `
  -- backend/python/database/baseline/schema.sha256
```

All commands must report no differences.

Also confirm:

```powershell
git diff --exit-code `
  origin/build/alembic-cutover-preparation-clean...HEAD `
  -- package-lock.json

git diff --exit-code `
  origin/build/alembic-cutover-preparation-clean...HEAD `
  -- backend/python/uv.lock
```

No dependency lock change is expected.

Search for runtime schema operations:

```powershell
git grep -n -E `
  "metadata\.create_all|metadata\.drop_all|alembic\.command\.upgrade|alembic\.command\.stamp|prisma migrate|prisma db push" `
  -- backend/python/app src
```

Expected:

```text
No automatic migration or runtime DDL in application code.
```

Documentation, migration scripts and tests may legitimately mention migration commands.

---

# 6. Install locked dependencies

From the repository root:

```powershell
npm ci
```

From the Python backend:

```powershell
cd backend/python
uv sync --frozen --extra dev
```

Do not regenerate:

```text
package-lock.json
uv.lock
```

unless an actual dependency inconsistency is proven.

---

# 7. Python quality gate

From `backend/python`:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy app scripts tests
uv run pytest -v
```

All checks must pass.

Record:

```text
passed tests
skipped tests
failed tests
total duration
```

Do not weaken Ruff, mypy, pytest or coverage configuration.

Do not add broad suppressions such as:

```text
# noqa
type: ignore
continue-on-error
|| true
```

unless the suppression is narrowly justified and covered by a regression test.

---

# 8. Cutover revision audit

Inspect:

```text
backend/python/migrations/versions/3d0001base_prisma_schema_baseline.py
backend/python/migrations/versions/3e0001cutover_alembic_ownership.py
```

Required graph:

```text
3d0001base
    ↓
3e0001cutover
```

Run:

```powershell
uv run alembic -c alembic.ini heads
uv run alembic -c alembic.ini history
uv run alembic -c alembic.ini show 3d0001base
uv run alembic -c alembic.ini show 3e0001cutover
```

Expected:

```text
revision count = 2
base count = 1
head count = 1
base = 3d0001base
head = 3e0001cutover
```

The cutover revision must contain:

```python
revision = "3e0001cutover"
down_revision = "3d0001base"

ownership_cutover = True
previous_migration_owner = "prisma"
new_migration_owner = "alembic"
baseline_revision = "3d0001base"
prisma_schema_impact = "none"
```

Its `upgrade()` must be a no-op.

It must not contain:

```text
op.create_table
op.drop_table
op.add_column
op.drop_column
op.alter_column
op.create_index
op.drop_index
op.execute
CREATE TYPE
ALTER TYPE
INSERT
UPDATE
DELETE
```

The downgrade must be explicitly blocked with a clear exception.

Run the committed graph and revision tests:

```powershell
uv run pytest `
  tests/test_alembic_configuration.py `
  tests/test_alembic_baseline.py `
  -v
```

---

# 9. Ownership manifest audit

Inspect:

```text
backend/python/database/schema_ownership.toml
```

Required top-level state:

```toml
schema_version = 6
current_migration_owner = "alembic"
target_migration_owner = "alembic"
cutover_status = "completed"
```

Required defaults:

```toml
[defaults]
current_owner = "alembic"
target_owner = "alembic"
cutover_status = "alembic_owned"
```

Required Alembic state:

```toml
[alembic]
state = "sole_migration_owner"
baseline_revision = "3d0001base"
cutover_revision = "3e0001cutover"
revision_count = 2
head_count = 1
```

Required cutover state:

```toml
[cutover]
phase = "completed"
baseline_revision = "3d0001base"
cutover_revision = "3e0001cutover"
previous_owner = "prisma"
current_owner = "alembic"
all_target_databases_stamped = true
all_target_databases_activated = true
deployment_command_switched = true
remote_databases_exist = false
completion_receipts_required = false
```

Required Prisma state:

```toml
[prisma_migrations]
state = "frozen_archive"
creation_enabled = false
deployment_enabled = false

[prisma_runtime]
state = "compatibility_mirror"
client_enabled = true
schema_is_migration_source = false
```

Confirm that all:

```text
30 application tables
27 PostgreSQL enums
```

inherit `alembic_owned`.

Run:

```powershell
uv run pytest tests/test_database_schema.py -v
```

---

# 10. Environment inventory audit

Inspect:

```text
backend/python/database/cutover/environments.toml
```

It must explicitly state that no persistent remote databases currently exist.

Expected semantics:

```toml
remote_databases_exist = false
required_environment_count = 0
```

A non-empty explanatory reason must be present.

Confirm:

- no staging environment is invented,
- no production environment is invented,
- no completed receipt is committed,
- no connection URL is committed,
- no hostname, credential, personal data or financial data is committed.

The policy must fail when:

- `remote_databases_exist` is changed to `true` without environments,
- required environment count becomes non-zero without evidence,
- a fake receipt is used to bypass policy.

---

# 11. Root deployment command audit

Inspect `package.json`.

Required deployment aliases:

```json
{
  "db:check": "cd backend/python && uv run python scripts/database_migrate.py check",
  "db:migrate": "cd backend/python && uv run python scripts/database_migrate.py upgrade",
  "db:deploy": "cd backend/python && uv run python scripts/database_migrate.py upgrade",
  "db:bootstrap": "cd backend/python && uv run python scripts/database_migrate.py bootstrap"
}
```

Prisma runtime commands must remain available:

```text
db:prisma:validate
db:prisma:generate
db:prisma:studio
```

A normal deployment command must not execute:

```text
prisma migrate dev
prisma migrate deploy
prisma migrate reset
prisma db push
```

Historical archive verification may exist only through:

```text
scripts/prisma-archive-verify.mjs
```

The wrapper must require:

```text
CI=true
ALLOW_FROZEN_PRISMA_ARCHIVE_DEPLOY=1
```

It must also refuse a non-empty target database.

---

# 12. Migration policy audit

Run:

```powershell
uv run python scripts/migration_policy.py --check
```

Expected result:

```text
Migration policy verification passed.
```

The policy must enforce:

- Alembic is current and target owner,
- cutover is completed,
- the revision head is `3e0001cutover`,
- revision count is exactly two,
- the frozen Prisma archive hash is unchanged,
- Prisma migration creation is disabled,
- Prisma migration deployment is disabled,
- root deploy aliases use Alembic,
- remote database inventory explicitly declares none,
- no runtime DDL exists,
- no automatic startup migration exists,
- no raw Prisma deployment command exists in workflows.

Run the negative unit tests:

```powershell
uv run pytest tests/test_migration_policy.py -v
```

Do not remove or weaken negative tests.

---

# 13. Prisma runtime compatibility

Return to repository root:

```powershell
cd ../..
npm run db:prisma:validate
npm run db:prisma:generate
npm test
npm run lint
npm run format:check
```

Prisma Client must remain usable.

Do not remove:

```text
@prisma/client
prisma/schema.prisma
PrismaClient imports
```

`schema.prisma` is a compatibility mirror, not the migration source of truth.

If `npm run build` can run with the available local environment, also execute:

```powershell
npm run build
```

If required secrets or external services prevent it, record the exact blocker. Do not invent placeholder production secrets.

---

# 14. Start an isolated PostgreSQL 16 database

Use a disposable local database only.

```powershell
docker rm -f finance-app-3eb-postgres 2>$null

docker run --name finance-app-3eb-postgres `
  -e POSTGRES_USER=postgres `
  -e POSTGRES_PASSWORD=postgres `
  -e POSTGRES_DB=finance_app_3eb `
  -p 55434:5432 `
  -d postgres:16
```

Wait until ready:

```powershell
do {
    Start-Sleep -Seconds 1
    docker exec finance-app-3eb-postgres `
      pg_isready -U postgres -d finance_app_3eb
} until ($LASTEXITCODE -eq 0)
```

Set:

```powershell
$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:55434/finance_app_3eb?schema=public"
$env:PGPASSWORD = "postgres"
```

Do not use any personal, staging or production database.

---

# 15. Historical frozen-Prisma bootstrap

The historical path must work only under explicit CI-style authorization and against an empty database.

From the repository root:

```powershell
$env:CI = "true"
$env:ALLOW_FROZEN_PRISMA_ARCHIVE_DEPLOY = "1"

npm run db:prisma:archive:verify
```

Expected:

- the frozen archive is verified,
- exactly the committed historical Prisma migrations are applied,
- the target schema had to be empty,
- no new Prisma migration is generated.

Clear the special authorization afterward:

```powershell
Remove-Item Env:ALLOW_FROZEN_PRISMA_ARCHIVE_DEPLOY
Remove-Item Env:CI
```

Verify counts:

```powershell
psql $env:DATABASE_URL -Atc @"
SELECT count(*)
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_type = 'BASE TABLE'
  AND table_name NOT IN ('_prisma_migrations', 'alembic_version');
"@
```

Expected:

```text
30
```

Verify PostgreSQL enum count:

```powershell
psql $env:DATABASE_URL -Atc @"
SELECT count(*)
FROM pg_type AS t
JOIN pg_namespace AS n ON n.oid = t.typnamespace
WHERE n.nspname = 'public'
  AND t.typtype = 'e';
"@
```

Expected:

```text
27
```

---

# 16. Existing inherited database cutover test

From `backend/python`:

```powershell
cd backend/python
```

Run pre-stamp verification:

```powershell
uv run python scripts/database_schema.py --check
uv run python scripts/sqlalchemy_schema.py --check
uv run python scripts/alembic_baseline.py --verify
```

Explicitly stamp only the inherited baseline:

```powershell
uv run alembic -c alembic.ini stamp 3d0001base
```

Verify current revision before upgrade:

```powershell
uv run alembic -c alembic.ini current
```

Expected:

```text
3d0001base
```

Do not require `alembic check` to pass while the database is intentionally behind head.

Upgrade through the normal deployment alias:

```powershell
cd ../..
npm run db:deploy
cd backend/python
```

After upgrade:

```powershell
uv run alembic -c alembic.ini current --check-heads
uv run alembic -c alembic.ini check
uv run python scripts/database_migrate.py check
uv run python scripts/database_schema.py --check
uv run python scripts/sqlalchemy_schema.py --check
```

Expected current head:

```text
3e0001cutover
```

Expected autogenerate result:

```text
No new upgrade operations detected.
```

The physical application schema must remain unchanged.

---

# 17. Data-preservation verification

Run:

```powershell
uv run pytest tests/test_alembic_integration.py -v
```

The test must prove:

- a representative application row exists before cutover,
- the row remains unchanged after upgrade,
- table count remains 30,
- enum count remains 27,
- revision changes from `3d0001base` to `3e0001cutover`,
- no business DDL is executed.

Do not move `alembic check` back before the upgrade to head. Alembic correctly rejects an intentionally out-of-date revision state.

---

# 18. Migration runner and advisory lock

Run:

```powershell
uv run pytest tests/test_database_migrate.py -v
uv run pytest tests/test_database_migrate_integration.py -v
```

Confirm:

- unknown revisions are rejected,
- unstamped inherited databases are rejected,
- the baseline revision is accepted as an upgrade starting point,
- the cutover head is accepted,
- two concurrent upgrade processes cannot run,
- the advisory lock is released after failure,
- migration output does not expose database passwords.

Run:

```powershell
uv run python scripts/database_migrate.py check
uv run python scripts/database_migrate.py upgrade
```

Both must pass on a database already at `3e0001cutover`.

---

# 19. Unknown revision rejection

Temporarily set a fake revision:

```powershell
psql $env:DATABASE_URL -c `
  "UPDATE public.alembic_version SET version_num = 'unknown_revision';"
```

Run:

```powershell
uv run python scripts/database_migrate.py check
uv run python scripts/database_migrate.py upgrade
```

Both must fail with a clear unknown-revision error.

Restore:

```powershell
psql $env:DATABASE_URL -c `
  "UPDATE public.alembic_version SET version_num = '3e0001cutover';"
```

Verify:

```powershell
uv run alembic -c alembic.ini current --check-heads
```

Do not leave the database in the fake state.

---

# 20. Clean Alembic-owned bootstrap

Create a second empty database:

```powershell
createdb `
  --host localhost `
  --port 55434 `
  --username postgres `
  finance_app_3eb_bootstrap
```

Set:

```powershell
$env:BOOTSTRAP_DATABASE_URL = "postgresql://postgres:postgres@localhost:55434/finance_app_3eb_bootstrap?schema=public"
$originalDatabaseUrl = $env:DATABASE_URL
$env:DATABASE_URL = $env:BOOTSTRAP_DATABASE_URL
```

Run the active bootstrap command:

```powershell
cd ../..
npm run db:bootstrap
cd backend/python
```

Expected sequence:

```text
empty public schema
canonical schema.sql loaded
baseline 3d0001base stamped
upgrade to 3e0001cutover
current --check-heads passed
canonical baseline passed
SQLAlchemy parity passed
```

Verify:

```powershell
uv run alembic -c alembic.ini current --check-heads
uv run alembic -c alembic.ini check
uv run python scripts/database_migrate.py check
uv run python scripts/database_schema.py --check
uv run python scripts/sqlalchemy_schema.py --check
```

Attempt bootstrap again:

```powershell
cd ../..
npm run db:bootstrap
cd backend/python
```

The second bootstrap must fail because the database is no longer empty.

Restore:

```powershell
$env:DATABASE_URL = $originalDatabaseUrl
```

---

# 21. CI workflow audit

Inspect:

```text
.github/workflows/database-schema.yml
```

Confirm that the workflow verifies:

1. locked Node and Python dependencies,
2. historical frozen Prisma bootstrap through the restricted wrapper,
3. Prisma validate and generate,
4. completed ownership policy,
5. canonical baseline,
6. SQLAlchemy parity,
7. inherited database stamp at `3d0001base`,
8. no-op upgrade to `3e0001cutover`,
9. data preservation,
10. advisory-lock behavior,
11. `current --check-heads`,
12. `alembic check`,
13. clean canonical bootstrap to cutover head.

No workflow may use raw:

```text
prisma migrate deploy
```

except inside the implementation of the restricted archive wrapper itself.

No temporary diagnostic or formatter workflow may remain.

---

# 22. Fix policy

When an actual Step 3E-B defect is found:

1. identify the root cause,
2. implement the smallest correct fix,
3. add or update a regression test,
4. rerun all relevant checks,
5. commit to:

```text
build/alembic-ownership-cutover
```

6. push normally.

Suggested commit messages:

```text
fix(db): preserve latest cutover preparation behavior
fix(db): correct Alembic ownership activation
test(db): cover ownership cutover regression
ci(db): enforce Alembic-only deployment
docs(db): clarify completed ownership state
```

Do not:

- merge PR #13,
- merge PR #15,
- force push,
- rewrite frozen Prisma migrations,
- modify `schema.prisma`,
- regenerate the canonical baseline,
- introduce a business schema change,
- add a third Alembic revision,
- remove Prisma Client,
- create fake environment receipts,
- run against a remote database,
- enable runtime startup migrations.

---

# 23. PR handling

## While PR #13 remains open

PR #15 must continue targeting:

```text
build/alembic-cutover-preparation-clean
```

Do not retarget it to `main` yet.

After synchronization and fixes, verify:

```powershell
gh pr view 15 --json state,isDraft,mergeable,baseRefName,headRefName,headRefOid
```

Expected:

```text
state = OPEN
draft = false
base = build/alembic-cutover-preparation-clean
head = build/alembic-ownership-cutover
mergeable = MERGEABLE
```

GitHub may require a short recalculation after push. Recheck rather than assuming a permanent conflict.

## If PR #13 becomes merged during this task

Only then:

```powershell
git fetch origin --prune
gh pr edit 15 --base main
```

Verify the Step 3E-B-only diff against `origin/main`.

Do not automatically merge PR #15.

After retargeting, rerun the entire relevant local audit and wait for both GitHub Actions on the exact new head.

---

# 24. GitHub Actions verification

After all commits are pushed:

```powershell
$finalHead = git rev-parse HEAD
gh run list --commit $finalHead --limit 10
```

Required workflows:

```text
Backend Python: success
Database Schema: success
```

Both must run on the exact final head.

Do not report success based only on an earlier SHA.

---

# 25. Final clean-state audit

Run:

```powershell
git status --short
git diff --check
git rev-parse HEAD
git rev-parse origin/build/alembic-ownership-cutover
```

Expected:

```text
working tree clean
no whitespace errors
local and remote head identical
```

Recheck the diff:

```powershell
git diff --stat origin/build/alembic-cutover-preparation-clean...HEAD
git diff --name-status origin/build/alembic-cutover-preparation-clean...HEAD
```

Confirm again:

```text
Prisma schema unchanged
Frozen Prisma migrations unchanged
Canonical schema unchanged
Canonical checksum unchanged
No business DDL
No data migration
No runtime migrations
No temporary files
```

---

# 26. Required final report

Return exactly this structure:

```text
STEP 3E-B FINAL LOCAL AUDIT

Repository:
VojLa/finance-app

Dependency PR:
#13

Dependency branch:
build/alembic-cutover-preparation-clean

Dependency state:
OPEN / MERGED

Dependency HEAD before synchronization:
<sha>

Target PR:
#15

Target branch:
build/alembic-ownership-cutover

PR base:
<actual base>

Expected starting HEAD:
8eddb3c517aa37016073dc677e85958eb20a1898

Actual starting HEAD:
<sha>

Final HEAD:
<sha>

Working tree clean:
PASS / FAIL

BRANCH SYNCHRONIZATION
Latest 3E-A merged into 3E-B:
PASS / FAIL

3E-A is ancestor of final 3E-B:
PASS / FAIL

Force push used:
YES / NO

Merge conflicts:
<list or None>

PYTHON QUALITY
Ruff lint:
PASS / FAIL

Ruff format:
PASS / FAIL

Mypy:
PASS / FAIL

Pytest:
PASS / FAIL

Passed tests:
<count>

Skipped tests:
<count>

Failed tests:
<count>

ALEMBIC REVISION GRAPH
Base revision:
<revision>

Head revision:
<revision>

Revision count:
<count>

Head count:
<count>

Cutover marker is no-op:
PASS / FAIL

Cutover downgrade blocked:
PASS / FAIL

Business DDL in cutover revision:
YES / NO

OWNERSHIP
schema_version:
<value>

current_migration_owner:
<value>

target_migration_owner:
<value>

cutover_status:
<value>

30 tables Alembic-owned:
PASS / FAIL

27 enums Alembic-owned:
PASS / FAIL

Prisma archive frozen:
PASS / FAIL

Prisma Client retained:
PASS / FAIL

Prisma schema is migration source:
YES / NO

ENVIRONMENT INVENTORY
Persistent remote databases exist:
YES / NO

Required environment count:
<count>

Fake receipts present:
YES / NO

Secrets present:
YES / NO

DEPLOYMENT COMMANDS
db:migrate uses Alembic:
PASS / FAIL

db:deploy uses Alembic:
PASS / FAIL

db:bootstrap uses Alembic:
PASS / FAIL

Raw Prisma deployment disabled:
PASS / FAIL

Historical wrapper restricted to CI:
PASS / FAIL

LEGACY DATABASE CUTOVER
Frozen Prisma archive applied:
PASS / FAIL

Application table count:
<count>

PostgreSQL enum count:
<count>

Canonical baseline before cutover:
PASS / FAIL

SQLAlchemy parity before cutover:
PASS / FAIL

Baseline stamp:
PASS / FAIL

Upgrade 3d0001base to 3e0001cutover:
PASS / FAIL

Data preserved:
PASS / FAIL

Canonical baseline after cutover:
PASS / FAIL

SQLAlchemy parity after cutover:
PASS / FAIL

Alembic current --check-heads:
PASS / FAIL

Alembic check:
PASS / FAIL

MIGRATION SAFETY
Unknown revision rejected:
PASS / FAIL

Unstamped inherited database rejected:
PASS / FAIL

Advisory lock:
PASS / FAIL

Lock released after failure:
PASS / FAIL

Runtime DDL absent:
PASS / FAIL

Automatic startup migrations absent:
PASS / FAIL

CLEAN BOOTSTRAP
Empty database requirement:
PASS / FAIL

Canonical schema loaded:
PASS / FAIL

Baseline stamped:
PASS / FAIL

Cutover head reached:
PASS / FAIL

Second bootstrap rejected:
PASS / FAIL

PRISMA RUNTIME
Prisma validate:
PASS / FAIL

Prisma generate:
PASS / FAIL

Frontend tests:
PASS / FAIL

Frontend lint:
PASS / FAIL

Frontend format:
PASS / FAIL

Frontend build:
PASS / FAIL / NOT RUN

SCOPE
Prisma schema unchanged:
PASS / FAIL

Prisma migrations unchanged:
PASS / FAIL

Canonical baseline unchanged:
PASS / FAIL

Canonical checksum unchanged:
PASS / FAIL

Dependency locks unchanged:
PASS / FAIL

Business schema unchanged:
PASS / FAIL

API/business logic unchanged:
PASS / FAIL

Temporary diagnostics absent:
PASS / FAIL

GITHUB
PR #15 state:
<state>

PR #15 base:
<base>

PR #15 mergeable:
YES / NO

Backend Python workflow:
PASS / FAIL / PENDING

Database Schema workflow:
PASS / FAIL / PENDING

Workflows verified on final HEAD:
YES / NO

FIXES
Changes made by Codex:
<list or None>

Commits added:
<list or None>

Commands not executed:
<list with reason or None>

Missing or incomplete items:
<list or None>

FINAL RESULT:
READY FOR RETARGET AFTER PR #13 MERGE
or
READY FOR MERGE
or
FIXES REQUIRED
or
BLOCKED

Blocking reasons:
<list or None>
```

Use:

```text
READY FOR RETARGET AFTER PR #13 MERGE
```

when all technical checks pass but PR #13 is still open.

Use:

```text
READY FOR MERGE
```

only when:

- PR #13 is merged,
- PR #15 targets `main`,
- the final diff is clean,
- both local audits pass,
- both GitHub workflows pass on the exact final head,
- the working tree is clean.

Do not merge either pull request.
