from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.db import models as database_models  # noqa: F401
from app.db.base import Base
from app.db.url import normalize_database_url
from scripts.sqlalchemy_schema import normalize_default

config = context.config
target_metadata = Base.metadata
EXCLUDED_TABLES = {"_prisma_migrations", "alembic_version"}


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
    if type_ == "schema":
        return name in {None, "public"}
    if type_ == "table":
        schema_name = parent_names.get("schema_name")
        return schema_name in {None, "public"} and name not in EXCLUDED_TABLES
    return True


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
        include_schemas=True,
        include_name=include_name,
        compare_type=True,
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
