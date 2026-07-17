from fastapi import FastAPI
from pydantic import BaseModel

from app.api.router import api_router
from app.config.settings import get_settings
from app.lifespan import lifespan


class RootResponse(BaseModel):
    service: str
    version: str
    endpoints: list[str]


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Python backend for orchestration, imports, jobs, and service APIs.",
        lifespan=lifespan,
    )
    app.include_router(api_router)

    @app.get("/", response_model=RootResponse)
    def root() -> RootResponse:
        return RootResponse(
            service="finance-app-backend",
            version=settings.app_version,
            endpoints=["/api/v1/health", "/api/v1/portfolio", "/docs", "/openapi.json"],
        )

    return app


app = create_app()
