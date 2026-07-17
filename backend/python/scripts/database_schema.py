from __future__ import annotations

import argparse
import difflib
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = PROJECT_ROOT / "database" / "baseline" / "schema.sql"
DEFAULT_CHECKSUM = PROJECT_ROOT / "database" / "baseline" / "schema.sha256"

_VOLATILE_PREFIXES = (
    "-- Dumped from database version ",
    "-- Dumped by pg_dump version ",
    "\\restrict ",
    "\\unrestrict ",
)
_VOLATILE_LINES = {
    "SET transaction_timeout = 0;",
}


def normalize_database_url(database_url: str) -> str:
    """Remove Prisma-only URI parameters that libpq does not understand."""
    parsed = urlsplit(database_url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query)
        if key != "schema"
    ]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def normalize_schema_dump(raw_dump: str) -> str:
    """Remove pg_dump version noise while preserving the physical schema definition."""
    normalized_lines: list[str] = []
    for raw_line in raw_dump.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw_line.rstrip()
        if line.startswith(_VOLATILE_PREFIXES) or line in _VOLATILE_LINES:
            continue
        normalized_lines.append(line)

    while normalized_lines and not normalized_lines[0]:
        normalized_lines.pop(0)
    while normalized_lines and not normalized_lines[-1]:
        normalized_lines.pop()

    return "\n".join(normalized_lines) + "\n"


def dump_schema(database_url: str, pg_dump: str = "pg_dump") -> str:
    command = [
        pg_dump,
        "--schema-only",
        "--schema=public",
        "--no-owner",
        "--no-privileges",
        "--quote-all-identifiers",
        "--exclude-table=public._prisma_migrations",
        normalize_database_url(database_url),
    ]
    result = subprocess.run(command, capture_output=True, check=False, text=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or "pg_dump failed without an error message"
        raise RuntimeError(detail)
    return normalize_schema_dump(result.stdout)


def schema_digest(schema: str) -> str:
    return hashlib.sha256(schema.encode("utf-8")).hexdigest()


def write_baseline(schema: str, baseline_path: Path, checksum_path: Path) -> None:
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(schema, encoding="utf-8", newline="\n")
    checksum_path.write_text(
        f"{schema_digest(schema)}  {baseline_path.name}\n",
        encoding="utf-8",
        newline="\n",
    )


def check_baseline(schema: str, baseline_path: Path, checksum_path: Path) -> int:
    if not baseline_path.exists() or not checksum_path.exists():
        print("Database baseline is missing. Generate it with --write.", file=sys.stderr)
        return 1

    expected = baseline_path.read_text(encoding="utf-8")
    checksum_parts = checksum_path.read_text(encoding="utf-8").strip().split()
    expected_digest = checksum_parts[0] if checksum_parts else ""
    actual_expected_digest = schema_digest(expected)

    if expected_digest != actual_expected_digest:
        print(
            "Committed database baseline checksum is invalid. Regenerate it with --write.",
            file=sys.stderr,
        )
        return 1

    if schema == expected:
        print("Database schema matches the committed baseline.")
        return 0

    print("Database schema drift detected:", file=sys.stderr)
    diff = difflib.unified_diff(
        expected.splitlines(),
        schema.splitlines(),
        fromfile=str(baseline_path),
        tofile="live-database-schema.sql",
        lineterm="",
    )
    for line in diff:
        print(line, file=sys.stderr)
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate or verify the canonical PostgreSQL schema baseline."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="Write schema.sql and checksum.")
    mode.add_argument(
        "--check",
        action="store_true",
        help="Compare the live schema to baseline.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="PostgreSQL connection URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--pg-dump",
        default=os.getenv("PG_DUMP", "pg_dump"),
        help="pg_dump executable. Defaults to PG_DUMP or pg_dump.",
    )
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--checksum", type=Path, default=DEFAULT_CHECKSUM)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.database_url:
        print("DATABASE_URL or --database-url is required.", file=sys.stderr)
        return 2

    try:
        schema = dump_schema(args.database_url, args.pg_dump)
    except FileNotFoundError:
        print(f"pg_dump executable not found: {args.pg_dump}", file=sys.stderr)
        return 2
    except RuntimeError as error:
        print(f"Unable to export database schema: {error}", file=sys.stderr)
        return 1

    if args.write:
        write_baseline(schema, args.baseline, args.checksum)
        print(f"Wrote database baseline to {args.baseline}.")
        return 0

    return check_baseline(schema, args.baseline, args.checksum)


if __name__ == "__main__":
    raise SystemExit(main())
