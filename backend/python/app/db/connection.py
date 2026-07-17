from collections.abc import AsyncIterator

import asyncpg
from fastapi import HTTPException, Request

from app.config.settings import get_settings


async def connect_database() -> asyncpg.Pool | None:
    settings = get_settings()
    if not settings.database_url:
        return None
    return await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)


async def close_database(pool: asyncpg.Pool | None) -> None:
    if pool is not None:
        await pool.close()


async def get_db(request: Request) -> AsyncIterator[asyncpg.Connection]:
    pool: asyncpg.Pool | None = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail="Database is not configured. Set DATABASE_URL for the Python backend.",
        )

    async with pool.acquire() as connection:
        yield connection
