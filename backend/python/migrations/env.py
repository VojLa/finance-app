from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from typing import Any

from alembic import context
from sqlalchemy import Index, MetaData, UniqueConstraint, pool
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.schema import BLANK_SCHEMA, Table

from app.db import models as database_models  # noqa: F401
from app.db.base import Base
from app.db.url import normalize_database_url
from scripts.sqlalchemy_schema import normalize_default

config = context.config
EXCLUDED_TABLES = {"_prisma_migrations", "alembic_version"}


def blank_referred_schema(
    table: Any,
    target_schema: str | None,
    constraint: Any,
    referred_schema: str | None,
) -> Any:
    del table, target_schema, constraint, referred_schema
    return BLANK_SCHEMA


def normalize_unique_indexes(table: Table) -> None:
    """Represent Prisma unique keys as PostgreSQL unique indexes for autogenerate."""
    for constraint in list(table.constraints):
        if not isinstance(constraint, UniqueConstraint):
            continue

        columns = [table.c[column.name] for column in constraint.columns]
        name = str(
            constraint.name or f"{table.name}_{'_'.join(column.name for column in columns)}_key"
        )
        table.constraints.remove(constraint)
        if not any(index.name == name for index in table.indexes):
            Index(name, *columns, unique=True)


def build_target_metadata() -> MetaData:
    """Copy the default public schema into Alembic's unqualified comparison namespace."""
    metadata = MetaData(naming_convention=Base.metadata.naming_convention)
    for table in Base.metadata.sorted_tables:
        table.to_metadata(
            metadata,
            schema=None,
            referred_schema_fn=blank_referred_schema,
        )

    for table in metadata.tables.values():
        for foreign_key in table.foreign_key_constraints:
            if foreign_key.onupdate is None:
                foreign_key.onupdate = "CASCADE"
        normalize_unique_indexes(table)

    return metadata


target_metadata = build_target_metadata()


def database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required for Alembic commands.")
    return normalize_database_url(value).render_as_string(hide_password=False)


def include_name(
    name: str | None,
    type_: str,
    parent_names: Mapping[str, str | None],
) -> bool:
    del parent_names
    if type_ == "table":
        return name not in EXCLUDED_TABLES
    return True


def compare_column_type(
    migration_context: Any,
    inspected_column: Any,
    metadata_column: Any,
    inspected_type: Any,
    metadata_type: Any,
) -> bool | None:
    del migration_context, inspected_column, metadata_column
    if isinstance(inspected_type, ENUM) and isinstance(metadata_type, ENUM):
        inspected_signature = (inspected_type.name, tuple(inspected_type.enums))
        metadata_signature = (metadata_type.name, tuple(metadata_type.enums))
        return inspected_signature != metadata_signature
    return None


def compare_server_default(
    migration_context: Any,
    inspected_column: Any,
    metadata_column: Any,
    inspected_default: str | None,
    metadata_default: Any,
    rendered_metadata_default: str | None,
) -> bool:
    del migration_context, inspected_column, metadata_column, metadata_default
    return normalize_default(inspected_default) != normalize_default(rendered_metadata_default)


def configure_context(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_schemas=False,
        include_name=include_name,
        compare_type=compare_column_type,
        compare_server_default=compare_server_default,
        version_table="alembic_version",
        version_table_schema="public",
        **kwargs,
    )


def run_migrations_offline() -> None:
    configure_context(
        url=database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    configure_context(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = database_url()
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
