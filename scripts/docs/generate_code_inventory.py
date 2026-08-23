"""Generate a deterministic inventory of production source files."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from common import (
    REPOSITORY_ROOT,
    check_argument,
    markdown_file_list,
    render_document,
    write_or_check,
)

OUTPUT_DIRECTORY = REPOSITORY_ROOT / "!docs" / "map" / "generated"
INDEX_OUTPUT = OUTPUT_DIRECTORY / "CODE-INVENTORY.md"
SOURCE_ROOTS = (Path("src"), Path("backend/python/app"), Path("backend/rust"))
SOURCE_SUFFIXES = {".py", ".rs", ".ts", ".tsx", ".js", ".mjs", ".jsx"}
EXCLUDED_DIRECTORIES = {
    "__pycache__",
    ".venv",
    "target",
    "node_modules",
    ".next",
    "generated",
}


def source_files() -> dict[str, list[Path]]:
    inventory: dict[str, list[Path]] = defaultdict(list)
    for relative_root in SOURCE_ROOTS:
        absolute_root = REPOSITORY_ROOT / relative_root
        if not absolute_root.exists():
            continue
        for path in absolute_root.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            relative = path.relative_to(REPOSITORY_ROOT)
            if any(part in EXCLUDED_DIRECTORIES for part in relative.parts):
                continue
            inventory[relative_root.as_posix()].append(relative)
    return {root: sorted(paths) for root, paths in sorted(inventory.items())}


def main() -> None:
    check = check_argument(__doc__ or "Generate code inventory.")
    inventory = source_files()
    total = sum(len(paths) for paths in inventory.values())
    index_sections = [
        "This inventory lists production source files only; tests and generated transport types are covered separately.",
        f"**Total files:** {total}",
    ]
    for root, paths in inventory.items():
        suffix = root.upper().replace("/", "-")
        output = OUTPUT_DIRECTORY / f"CODE-INVENTORY-{suffix}.md"
        write_or_check(
            output,
            render_document(
                "generate_code_inventory",
                f"Code Inventory — {root}",
                f"**Files:** {len(paths)}\n\n{markdown_file_list(paths)}",
            ),
            check=check,
        )
        index_sections.append(f"- [`{root}/`]({output.name}) — {len(paths)} files")
    write_or_check(
        INDEX_OUTPUT,
        render_document(
            "generate_code_inventory", "Code Inventory", "\n\n".join(index_sections)
        ),
        check=check,
    )


if __name__ == "__main__":
    main()
