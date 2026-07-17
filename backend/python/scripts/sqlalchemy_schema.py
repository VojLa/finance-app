from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Boolean, Integer, Numeric, Text, UniqueConstraint, inspect
from sqlalchemy.dialects.postgresql import ENUM, JSONB, TIMESTAMP
from sqlalchemy.engine import Inspector
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import Column, Table

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import models as database_models  # noqa: E402,F401
from app.db.base import Base  # noqa: E402
from app.db.url import normalize_database_url  # noqa: E402

EXCLUDED_TABLES = {"_prisma_migrations"}


def normalize_default(value: object | None) -> str | None:
    if value is None:
        return None

    normalized = " ".join(str(value).strip().split()).lower()
    normalized = normalized.replace('"public".', "").replace("public.", "")
    normalized = re.sub(r'::"([^"]+)"', r"::\1", normalized)
    normalized = normalized.replace("now()", "current_timestamp")
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    return normalized


def type_signature(column_type: object) -> str:
    if isinstance(column_type, ENUM):
        labels = ",".join(column_type.enums)
        return f"enum:{column_type.name}:{labels}"
    if isinstance(column_type, Numeric):
        return f"numeric:{column_type.precision}:{column_type.scale}"
    if isinstance(column_type, TIMESTAMP):
        return f"timestamp:{column_type.precision}:{column_type.timezone}"
    if isinstance(column_type, JSONB):
        return "jsonb"
    if isinstance(column_type, Text):
        return "text"
    if isinstance(column_type, Boolean):
        return "boolean"
    if isinstance(column_type, Integer):
        return "integer"
    return str(column_type).lower()


def _sorted_columns(columns: Sequence[str | None] | None) -> list[str]:
    return [column for column in columns or [] if column is not None]


def _server_default(column: Column[Any]) -> object | None:
    if column.server_default is None:
        return None
    return getattr(column.server_default, "arg", column.server_default)


def local_table_snapshot(table: Table) -> dict[str, Any]:
    columns = [
        {
            "name": column.name,
            "type": type_signature(column.type),
            "nullable": column.nullable,
            "default": normalize_default(_server_default(column)),
        }
        for column in table.columns
    ]

    foreign_keys = []
    for constraint in table.foreign_key_constraints:
        elements = list(constraint.elements)
        foreign_keys.append(
            {
                "columns": [element.parent.name for element in elements],
                "referred_schema": elements[0].column.table.schema if elements else None,
                "referred_table": elements[0].column.table.name if elements else None,
                "referred_columns": [element.column.name for element in elements],
                "ondelete": constraint.ondelete.upper() if constraint.ondelete else None,
            }
        )

    unique_constraints = [
        [column.name for column in constraint.columns]
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    ]

    indexes = [
        {
            "columns": [column.name for column in index.columns],
            "unique": index.unique,
        }
        for index in table.indexes
    ]

    return {
        "columns": columns,
        "primary_key": [column.name for column in table.primary_key.columns],
        "foreign_keys": sorted(
            foreign_keys,
            key=lambda item: (item["columns"], item["referred_table"] or ""),
        ),
        "unique_constraints": sorted(unique_constraints),
        "indexes": sorted(indexes, key=lambda item: (item["columns"], item["unique"])),
    }


def local_snapshot() -> dict[str, Any]:
    tables = {
        table.name: local_table_snapshot(table)
        for table in sorted(Base.metadata.tables.values(), key=lambda item: item.name)
    }
    enums = {
        column.type.name: list(column.type.enums)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, ENUM) and column.type.name is not None
    }
    return {"tables": tables, "enums": dict(sorted(enums.items()))}


def reflected_table_snapshot(inspector: Inspector, table_name: str) -> dict[str, Any]:
    columns = [
        {
            "name": column["name"],
            "type": type_signature(column["type"]),
            "nullable": column["nullable"],
            "default": normalize_default(column.get("default")),
        }
        for column in inspector.get_columns(table_name, schema="public")
    ]

    foreign_keys = [
        {
            "columns": _sorted_columns(foreign_key.get("constrained_columns")),
            "referred_schema": foreign_key.get("referred_schema") or "public",
            "referred_table": foreign_key.get("referred_table"),
            "referred_columns": _sorted_columns(foreign_key.get("referred_columns")),
            "ondelete": (
                str(foreign_key.get("options", {}).get("ondelete")).upper()
                if foreign_key.get("options", {}).get("ondelete")
                else None
            ),
        }
        for foreign_key in inspector.get_foreign_keys(table_name, schema="public")
    ]

    unique_constraints = [
        _sorted_columns(constraint.get("column_names"))
        for constraint in inspector.get_unique_constraints(table_name, schema="public")
    ]

    indexes = [
        {
            "columns": _sorted_columns(index.get("column_names")),
            "unique": bool(index.get("unique")),
        }
        for index in inspector.get_indexes(table_name, schema="public")
        if not index.get("duplicates_constraint")
    ]

    primary_key = inspector.get_pk_constraint(table_name, schema="public")
    return {
        "columns": columns,
        "primary_key": _sorted_columns(primary_key.get("constrained_columns")),
        "foreign_keys": sorted(
            foreign_keys,
            key=lambda item: (item["columns"], item["referred_table"] or ""),
        ),
        "unique_constraints": sorted(unique_constraints),
        "indexes": sorted(indexes, key=lambda item: (item["columns"], item["unique"])),
    }


def reflected_snapshot(inspector: Inspector) -> dict[str, Any]:
    table_names = sorted(
        table_name
        for table_name in inspector.get_table_names(schema="public")
        if table_name not in EXCLUDED_TABLES
    )
    tables = {
        table_name: reflected_table_snapshot(inspector, table_name) for table_name in table_names
    }
    postgresql_inspector = cast(Any, inspector)
    enums = {
        enum["name"]: list(enum["labels"])
        for enum in postgresql_inspector.get_enums(schema="public")
    }
    return {"tables": tables, "enums": dict(sorted(enums.items()))}


async def live_snapshot(database_url: str) -> dict[str, Any]:
    engine = create_async_engine(normalize_database_url(database_url))
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(
                lambda sync_connection: reflected_snapshot(inspect(sync_connection))
            )
    finally:
        await engine.dispose()


def render(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True) + "\n"


def compare_snapshots(expected: dict[str, Any], actual: dict[str, Any]) -> int:
    expected_text = render(expected)
    actual_text = render(actual)
    if expected_text == actual_text:
        print("SQLAlchemy metadata matches the Prisma-migrated PostgreSQL schema.")
        return 0

    print("SQLAlchemy metadata drift detected:", file=sys.stderr)
    for line in difflib.unified_diff(
        actual_text.splitlines(),
        expected_text.splitlines(),
        fromfile="live-postgresql-schema.json",
        tofile="sqlalchemy-metadata.json",
        lineterm="",
    ):
        print(line, file=sys.stderr)
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print or verify SQLAlchemy metadata against PostgreSQL reflection."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--print", action="store_true", dest="print_metadata")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="PostgreSQL connection URL. Defaults to DATABASE_URL.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    metadata = local_snapshot()

    if args.print_metadata:
        print(render(metadata), end="")
        return 0

    if not args.database_url:
        print("DATABASE_URL or --database-url is required.", file=sys.stderr)
        return 2

    reflected = asyncio.run(live_snapshot(args.database_url))
    return compare_snapshots(metadata, reflected)


if __name__ == "__main__":
    raise SystemExit(main())
