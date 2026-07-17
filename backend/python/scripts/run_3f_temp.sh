#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BACKEND_ROOT="$REPOSITORY_ROOT/backend/python"
TRACE_FILE="/tmp/3f-lifecycle-report.txt"

exec > >(tee "$TRACE_FILE") 2>&1
set -x

preserve_failure_trace() {
  local status=$?
  if [[ $status -eq 0 ]]; then
    return
  fi
  set +e
  cd "$REPOSITORY_ROOT"
  git reset --hard HEAD
  cp "$TRACE_FILE" backend/python/3f-lifecycle-report.txt
  printf '\nexit_status=%s\n' "$status" >> backend/python/3f-lifecycle-report.txt
  git config user.name "github-actions[bot]"
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
  git add backend/python/3f-lifecycle-report.txt
  git commit -m "chore: capture 3F lifecycle failure"
  git push origin HEAD:feat/alembic-account-notes
  exit "$status"
}
trap preserve_failure_trace EXIT

cd "$BACKEND_ROOT"
uv run python scripts/fix_implement_3f_temp.py
uv run python scripts/implement_3f_temp.py
uv run ruff check . --fix
uv run ruff format .

cd "$REPOSITORY_ROOT"
npx prisma format
npx prettier --write .github/workflows/database-schema.yml

cd "$BACKEND_ROOT"
python - <<'PY'
from pathlib import Path

source = Path("database/baseline/schema.sql").read_text(encoding="utf-8")
Path(".bootstrap-3f.sql").write_text(
    source.replace('CREATE SCHEMA "public";\n', "", 1),
    encoding="utf-8",
    newline="\n",
)
PY
psql --set=ON_ERROR_STOP=1 --dbname="$DATABASE_URL" --file=.bootstrap-3f.sql
rm .bootstrap-3f.sql
uv run alembic -c alembic.ini stamp 3d0001base
uv run alembic -c alembic.ini upgrade head
uv run python scripts/database_schema.py --write --revision 3f0001acctnote
uv run python scripts/database_schema.py --check --revision 3f0001acctnote
uv run python scripts/sqlalchemy_schema.py --check
uv run alembic -c alembic.ini check

cd "$REPOSITORY_ROOT"
dropdb --host localhost --username postgres --force finance_app
createdb --host localhost --username postgres finance_app
ALLOW_FROZEN_PRISMA_ARCHIVE_DEPLOY=1 npm run db:prisma:archive:verify

cd "$BACKEND_ROOT"
uv run ruff check .
uv run ruff format --check .
uv run mypy app scripts tests
uv run python scripts/migration_policy.py --check
uv run pytest \
  tests/test_database_schema.py \
  tests/test_database_models.py \
  tests/test_database_url.py \
  tests/test_sqlalchemy_schema.py \
  tests/test_alembic_configuration.py \
  tests/test_alembic_baseline.py \
  tests/test_migration_policy.py \
  tests/test_database_migrate.py

uv run python scripts/database_schema.py --check --revision 3d0001base
uv run python scripts/alembic_baseline.py --verify
uv run pytest tests/test_alembic_integration.py -v
uv run pytest \
  tests/test_sqlalchemy_schema_parity.py \
  tests/test_sqlalchemy_persistence.py \
  tests/test_database_migrate_integration.py \
  -v
uv run python scripts/database_migrate.py check
uv run python scripts/database_schema.py --check --revision 3f0001acctnote
uv run python scripts/sqlalchemy_schema.py --check
uv run alembic -c alembic.ini current --check-heads
uv run alembic -c alembic.ini check

createdb --host localhost --username postgres finance_app_bootstrap
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/finance_app_bootstrap"
uv run python scripts/database_migrate.py bootstrap
uv run python scripts/database_migrate.py check
uv run python scripts/database_schema.py --check --revision 3f0001acctnote
uv run python scripts/sqlalchemy_schema.py --check

cd "$REPOSITORY_ROOT"
npm run db:prisma:validate
npm run db:prisma:generate
npm test
npm run lint

rm -f backend/python/scripts/implement_3f_temp.py
rm -f backend/python/scripts/fix_implement_3f_temp.py
rm -f backend/python/scripts/run_3f_temp.sh
rm -f backend/python/3f-format-report.txt
rm -f backend/python/3f-lifecycle-report.txt
rm -f .github/workflows/implement-3f.yml

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add .
git diff --cached --check
git commit -m "feat(db): add first Alembic-owned schema migration"
git push origin HEAD:feat/alembic-account-notes
