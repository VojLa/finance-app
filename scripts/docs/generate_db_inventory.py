"""Generate a deterministic inventory of SQLAlchemy model and migration files."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from common import (
    REPOSITORY_ROOT,
    check_argument,
    markdown_file_list,
    render_document,
    write_or_check,
)

OUTPUT = REPOSITORY_ROOT / "!docs" / "map" / "generated" / "DB-INVENTORY.md"
MODEL_ROOT = REPOSITORY_ROOT / "backend" / "python" / "app" / "db" / "models"
MIGRATION_ROOT = REPOSITORY_ROOT / "backend" / "python" / "migrations" / "versions"
SCHEMA_ARTIFACT_ROOT = REPOSITORY_ROOT / "backend" / "python" / "database" / "revisions"
REVISION_PATTERN = re.compile(
    r"^revision:\s*str\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE
)


def model_classes(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return sorted(node.name for node in tree.body if isinstance(node, ast.ClassDef))


def migration_revision(path: Path) -> str:
    match = REVISION_PATTERN.search(path.read_text(encoding="utf-8"))
    return match.group(1) if match else "unknown"


def main() -> None:
    check = check_argument(__doc__ or "Generate database inventory.")
    models: dict[Path, list[str]] = {}
    for path in sorted(MODEL_ROOT.glob("*.py")):
        if path.name == "__init__.py":
            continue
        models[path.relative_to(REPOSITORY_ROOT)] = model_classes(path)

    model_lines = ["| Model file | Classes |", "| --- | --- |"]
    for path, classes in models.items():
        model_lines.append(
            f"| `{path.as_posix()}` | {', '.join(f'`{name}`' for name in classes) or '—'} |"
        )

    migrations = sorted(MIGRATION_ROOT.glob("*.py"))
    migration_lines = ["| Revision | Migration file |", "| --- | --- |"]
    for path in migrations:
        migration_lines.append(
            f"| `{migration_revision(path)}` | `{path.relative_to(REPOSITORY_ROOT).as_posix()}` |"
        )

    artifacts = sorted(
        path.relative_to(REPOSITORY_ROOT)
        for path in SCHEMA_ARTIFACT_ROOT.glob("*/schema.sql")
    )
    sections = [
        "SQLAlchemy model classes are an inventory, not a schema specification. Alembic and the checked schema artifacts remain the executable schema authority.",
        f"## SQLAlchemy model files ({len(models)})\n\n" + "\n".join(model_lines),
        f"## Alembic revisions ({len(migrations)})\n\n" + "\n".join(migration_lines),
        f"## Revision schema artifacts ({len(artifacts)})\n\n"
        + markdown_file_list(artifacts),
    ]
    write_or_check(
        OUTPUT,
        render_document(
            "generate_db_inventory",
            "Database and Model Inventory",
            "\n\n".join(sections),
        ),
        check=check,
    )


if __name__ == "__main__":
    main()
