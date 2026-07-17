import asyncpg


async def check_database(pool: asyncpg.Pool | None) -> bool:
    if pool is None:
        return False

    try:
        async with pool.acquire() as connection:
            result = await connection.fetchval("SELECT 1")
    except (asyncpg.PostgresError, OSError):
        return False

    return result == 1
