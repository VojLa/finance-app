"""Shared deterministic output helpers for documentation inventory scripts."""

from __future__ import annotations

import argparse
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIRECTORY = REPOSITORY_ROOT / "!docs" / "map" / "generated"


def check_argument(description: str) -> bool:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the tracked generated file differs from current output.",
    )
    return parser.parse_args().check


def render_document(generator_name: str, title: str, body: str) -> str:
    return (
        "<!--\n"
        f"  GENERATED FILE — created by scripts/docs/{generator_name}.py.\n"
        "  Do not edit manually; run the generator instead.\n"
        "-->\n\n"
        f"# {title}\n\n"
        f"{body.rstrip()}\n"
    )


def write_or_check(output: Path, content: str, *, check: bool) -> None:
    if check:
        existing = output.read_text(encoding="utf-8") if output.exists() else None
        if existing != content:
            relative = output.relative_to(REPOSITORY_ROOT).as_posix()
            raise SystemExit(
                f"{relative} is stale. Run the corresponding scripts/docs generator."
            )
        print(f"Current: {output.relative_to(REPOSITORY_ROOT).as_posix()}")
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8", newline="\n")
    print(f"Generated: {output.relative_to(REPOSITORY_ROOT).as_posix()}")


def markdown_file_list(paths: list[Path]) -> str:
    if not paths:
        return "_None._"
    return "\n".join(f"- `{path.as_posix()}`" for path in paths)
