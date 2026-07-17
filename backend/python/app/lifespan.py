from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config.settings import Settings, get_settings
from app.db.connection import close_database, connect_database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = getattr(app.state, "settings", None) or get_settings()
    app.state.db_pool = await connect_database(settings)
    try:
        yield
    finally:
        await close_database(getattr(app.state, "db_pool", None))
