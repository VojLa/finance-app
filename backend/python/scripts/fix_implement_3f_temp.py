from pathlib import Path

path = Path(__file__).with_name("implement_3f_temp.py")
source = path.read_text(encoding="utf-8")

replacements = (
    (
        '    account_end = prisma_source.index("\\n}", account_start)\n',
        '    account_end = prisma_source.index("\\\\n}", account_start)\n',
        "generated Prisma model boundary check",
    ),
    (
        '    "from alembic.script import ScriptDirectory\\n\\nfrom scripts import database_schema\\n",\n',
        '    "from alembic.script import ScriptDirectory\\n\\n"\n'
        '    "if __package__ in (None, \\\"\\\"):\\n"\n'
        '    "    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\\n"\n'
        '    "\\n"\n'
        '    "from scripts import database_schema\\n",\n',
        "migration policy direct-execution import",
    ),
)

for old, new, label in replacements:
    if source.count(old) != 1:
        raise RuntimeError(f"Unable to patch {label}.")
    source = source.replace(old, new, 1)

path.write_text(source, encoding="utf-8", newline="\n")
