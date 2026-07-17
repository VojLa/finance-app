from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.connection import close_database, connect_database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.db_pool = await connect_database()
    try:
        yield
    finally:
        await close_database(getattr(app.state, "db_pool", None))
