from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import Settings
from app.db.url import normalize_database_url


@dataclass(frozen=True, slots=True)
class Database:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]


def create_database(settings: Settings) -> Database | None:
    if not settings.database_url:
        return None

    engine = create_async_engine(
        normalize_database_url(settings.database_url),
        pool_size=5,
        max_overflow=0,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
    )
    return Database(engine=engine, session_factory=session_factory)


async def close_database(database: Database | None) -> None:
    if database is not None:
        await database.engine.dispose()


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database | None = getattr(request.app.state, "database", None)
    if database is None:
        raise HTTPException(
            status_code=503,
            detail="Database is not configured. Set DATABASE_URL for the Python backend.",
        )

    async with database.session_factory() as session:
        yield session
