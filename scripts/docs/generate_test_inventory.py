"""Generate a deterministic inventory of TypeScript and Python test files."""

from __future__ import annotations

from pathlib import Path

from common import (
    REPOSITORY_ROOT,
    check_argument,
    markdown_file_list,
    render_document,
    write_or_check,
)

OUTPUT = REPOSITORY_ROOT / "!docs" / "map" / "generated" / "TEST-INVENTORY.md"


def tests_under(relative_root: Path, patterns: tuple[str, ...]) -> list[Path]:
    root = REPOSITORY_ROOT / relative_root
    files = {path for pattern in patterns for path in root.rglob(pattern)}
    return sorted(path.relative_to(REPOSITORY_ROOT) for path in files if path.is_file())


def main() -> None:
    check = check_argument(__doc__ or "Generate test inventory.")
    frontend = tests_under(
        Path("src"), ("*.test.ts", "*.test.tsx", "*.spec.ts", "*.spec.tsx")
    )
    backend = tests_under(Path("backend/python/tests"), ("test_*.py",))
    sections = [
        f"## Frontend and adapter tests ({len(frontend)})\n\n{markdown_file_list(frontend)}",
        f"## Python backend tests ({len(backend)})\n\n{markdown_file_list(backend)}",
        f"**Total test files:** {len(frontend) + len(backend)}",
    ]
    write_or_check(
        OUTPUT,
        render_document(
            "generate_test_inventory", "Test Inventory", "\n\n".join(sections)
        ),
        check=check,
    )


if __name__ == "__main__":
    main()
