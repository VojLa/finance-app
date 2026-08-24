"""Check generated documentation freshness and local Markdown links."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

from common import REPOSITORY_ROOT

GENERATORS = (
    "generate_code_inventory.py",
    "generate_api_inventory.py",
    "generate_db_inventory.py",
    "generate_test_inventory.py",
    "generate_module_inventory.py",
)
DOCUMENTATION_ROOTS = ("!docs", "!planning", "!user-docs")
MAXIMUM_DOC_LINES = 200
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
EXTERNAL_LINK_PREFIXES = ("#", "http://", "https://", "mailto:")


def check_generated_files() -> list[str]:
    errors: list[str] = []
    for generator in GENERATORS:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name(generator)), "--check"],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
        )
        if result.returncode:
            errors.append(
                result.stderr.strip() or result.stdout.strip() or f"{generator} failed"
            )
    return errors


def local_link_errors() -> list[str]:
    errors: list[str] = []
    for root_name in DOCUMENTATION_ROOTS:
        root = REPOSITORY_ROOT / root_name
        if not root.exists():
            continue
        for document in root.rglob("*.md"):
            content = document.read_text(encoding="utf-8")
            for match in MARKDOWN_LINK.finditer(content):
                target = unquote(match.group(1).split("#", maxsplit=1)[0].strip())
                if not target or target.startswith(EXTERNAL_LINK_PREFIXES):
                    continue
                target_path = (document.parent / target).resolve()
                if not target_path.exists():
                    errors.append(
                        f"{document.relative_to(REPOSITORY_ROOT).as_posix()}: missing link target {target}"
                    )
    return errors


def document_length_errors() -> list[str]:
    docs_root = REPOSITORY_ROOT / "!docs"
    errors: list[str] = []
    for document in docs_root.rglob("*.md"):
        if "generated" in document.relative_to(docs_root).parts:
            continue
        line_count = len(document.read_text(encoding="utf-8").splitlines())
        if line_count > MAXIMUM_DOC_LINES:
            errors.append(
                f"{document.relative_to(REPOSITORY_ROOT).as_posix()}: "
                f"{line_count} lines exceeds the {MAXIMUM_DOC_LINES}-line limit"
            )
    return errors


def documentation_directory_errors() -> list[str]:
    errors: list[str] = []
    for root_name in DOCUMENTATION_ROOTS:
        docs_root = REPOSITORY_ROOT / root_name
        if not docs_root.exists():
            continue
        for directory in docs_root.rglob("*"):
            if directory.is_dir() and not (directory / "README.md").is_file():
                errors.append(
                    f"{directory.relative_to(REPOSITORY_ROOT).as_posix()}: missing README.md"
                )
    return errors


def main() -> None:
    errors = [
        *check_generated_files(),
        *local_link_errors(),
        *document_length_errors(),
        *documentation_directory_errors(),
    ]
    if errors:
        print("Documentation checks failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        raise SystemExit(1)
    print("Documentation checks passed.")


if __name__ == "__main__":
    main()
