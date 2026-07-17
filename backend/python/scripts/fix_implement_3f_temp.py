from pathlib import Path

path = Path(__file__).with_name("implement_3f_temp.py")
source = path.read_text(encoding="utf-8")
old = '''replace_once(
    database_migrate,
    "    alembic_baseline.verify_canonical_baseline(database_url, pg_dump)\\n"
    "    alembic_baseline.verify_sqlalchemy_parity(database_url)\\n",
    "    current_revision = state.version_revisions[0]\\n"
    "    alembic_baseline.verify_revision_schema(database_url, pg_dump, current_revision)\\n"
    "    if require_head:\\n"
    "        alembic_baseline.verify_sqlalchemy_parity(database_url)\\n",
)
'''
new = '''runner_source = database_migrate.read_text(encoding="utf-8")
runner_old = (
    "    alembic_baseline.verify_canonical_baseline(database_url, pg_dump)\\n"
    "    alembic_baseline.verify_sqlalchemy_parity(database_url)\\n"
)
runner_new = (
    "    current_revision = state.version_revisions[0]\\n"
    "    alembic_baseline.verify_revision_schema(database_url, pg_dump, current_revision)\\n"
    "    if require_head:\\n"
    "        alembic_baseline.verify_sqlalchemy_parity(database_url)\\n"
)
if runner_old not in runner_source:
    raise RuntimeError("Prepared database verification block is missing.")
database_migrate.write_text(
    runner_source.replace(runner_old, runner_new, 1),
    encoding="utf-8",
    newline="\\n",
)
'''
if source.count(old) != 1:
    raise RuntimeError("Unable to patch the temporary 3F implementation script.")
path.write_text(source.replace(old, new, 1), encoding="utf-8", newline="\n")
