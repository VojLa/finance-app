from fastapi import FastAPI
from pydantic import BaseModel

from app.api.router import api_router
from app.core.db import create_pool


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
    app.include_router(api_router)

    @app.get("/", response_model=RootResponse)
    def root() -> RootResponse:
        return RootResponse(
            service="finance-app-backend",
            version="0.1.0",
            endpoints=["/api/v1/health", "/api/v1/portfolio", "/docs", "/openapi.json"],
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
