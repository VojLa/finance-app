from pathlib import Path

path = Path(__file__).with_name("implement_3f_temp.py")
source = path.read_text(encoding="utf-8")
old = '    account_end = prisma_source.index("\\n}", account_start)\n'
new = '    account_end = prisma_source.index("\\\\n}", account_start)\n'
if source.count(old) != 1:
    raise RuntimeError("Unable to patch the generated Prisma model boundary check.")
path.write_text(source.replace(old, new, 1), encoding="utf-8", newline="\n")
