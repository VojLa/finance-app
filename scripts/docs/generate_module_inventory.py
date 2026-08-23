"""Generate a deterministic inventory of top-level application modules."""

from __future__ import annotations

from pathlib import Path

from common import (
    REPOSITORY_ROOT,
    check_argument,
    markdown_file_list,
    render_document,
    write_or_check,
)

OUTPUT = REPOSITORY_ROOT / "!docs" / "map" / "generated" / "MODULE-INVENTORY.md"
MODULE_ROOTS = (Path("backend/python/app/modules"), Path("src/modules"))


def module_directories(relative_root: Path) -> list[Path]:
    root = REPOSITORY_ROOT / relative_root
    return sorted(
        path.relative_to(REPOSITORY_ROOT)
        for path in root.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    )


def main() -> None:
    check = check_argument(__doc__ or "Generate module inventory.")
    sections = []
    for root in MODULE_ROOTS:
        modules = module_directories(root)
        sections.append(
            f"## `{root.as_posix()}/` ({len(modules)})\n\n{markdown_file_list(modules)}"
        )
    write_or_check(
        OUTPUT,
        render_document(
            "generate_module_inventory", "Module Inventory", "\n\n".join(sections)
        ),
        check=check,
    )


if __name__ == "__main__":
    main()
