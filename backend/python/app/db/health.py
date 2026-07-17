from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.connection import Database


async def check_database(database: Database | None) -> bool:
    if database is None:
        return False

    try:
        async with database.engine.connect() as connection:
            result = await connection.scalar(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        return False

    return result == 1
