"""Generate a deterministic inventory of SQLAlchemy model and migration files."""

from __future__ import annotations

import ast
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


def model_classes(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return sorted(node.name for node in tree.body if isinstance(node, ast.ClassDef))


def migration_revision(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "revision":
                value = node.value
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "revision" for target in node.targets
        ):
            value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return "unknown"


def markdown_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    """Render a deterministic table in the same padded form as Prettier."""
    widths = [
        max(3, len(header), *(len(row[index]) for row in rows))
        for index, header in enumerate(headers)
    ]

    def render_row(cells: tuple[str, ...]) -> str:
        return (
            "| " + " | ".join(cell.ljust(widths[index]) for index, cell in enumerate(cells)) + " |"
        )

    separator = tuple("-" * width for width in widths)
    return "\n".join(
        [render_row(headers), render_row(separator), *(render_row(row) for row in rows)]
    )


def main() -> None:
    check = check_argument(__doc__ or "Generate database inventory.")
    models: dict[Path, list[str]] = {}
    for path in sorted(MODEL_ROOT.glob("*.py")):
        if path.name == "__init__.py":
            continue
        models[path.relative_to(REPOSITORY_ROOT)] = model_classes(path)

    model_rows = [
        (
            f"`{path.as_posix()}`",
            ", ".join(f"`{name}`" for name in classes) or "—",
        )
        for path, classes in models.items()
    ]

    migrations = sorted(MIGRATION_ROOT.glob("*.py"))
    migration_rows = [
        (
            f"`{migration_revision(path)}`",
            f"`{path.relative_to(REPOSITORY_ROOT).as_posix()}`",
        )
        for path in migrations
    ]

    artifacts = sorted(
        path.relative_to(REPOSITORY_ROOT) for path in SCHEMA_ARTIFACT_ROOT.glob("*/schema.sql")
    )
    sections = [
        "SQLAlchemy model classes are an inventory, not a schema specification. Alembic and the checked schema artifacts remain the executable schema authority.",
        f"## SQLAlchemy model files ({len(models)})\n\n"
        + markdown_table(("Model file", "Classes"), model_rows),
        f"## Alembic revisions ({len(migrations)})\n\n"
        + markdown_table(("Revision", "Migration file"), migration_rows),
        f"## Revision schema artifacts ({len(artifacts)})\n\n" + markdown_file_list(artifacts),
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
