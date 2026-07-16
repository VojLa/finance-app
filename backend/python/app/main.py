from fastapi import FastAPI
from pydantic import BaseModel

from app.core.db import create_pool
from app.routers.health import router as health_router
from app.routers.portfolio import router as portfolio_router


class RootResponse(BaseModel):
    service: str
    version: str
    endpoints: list[str]


def create_app() -> FastAPI:
    app = FastAPI(
        title="Finance App Backend",
        version="0.1.0",
        description="Python backend for orchestration, imports, jobs, and service APIs.",
    )
    app.include_router(health_router)
    app.include_router(portfolio_router)

    @app.get("/", response_model=RootResponse)
    def root() -> RootResponse:
        return RootResponse(
            service="finance-app-backend",
            version="0.1.0",
            endpoints=["/health", "/portfolio", "/docs", "/openapi.json"],
        )

    @app.on_event("startup")
    async def startup() -> None:
        app.state.db_pool = await create_pool()

    @app.on_event("shutdown")
    async def shutdown() -> None:
        pool = getattr(app.state, "db_pool", None)
        if pool is not None:
            await pool.close()

    return app


app = create_app()
