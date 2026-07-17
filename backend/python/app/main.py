from fastapi import FastAPI
from pydantic import BaseModel

from app.api.router import api_router, legacy_router
from app.config.settings import Settings, get_settings
from app.lifespan import lifespan
from app.shared.error_handlers import register_exception_handlers
from app.shared.logging import configure_logging
from app.shared.request_context import RequestContextMiddleware


class RootResponse(BaseModel):
    service: str
    version: str
    endpoints: list[str]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(json_logs=settings.environment != "development")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Python backend for orchestration, imports, jobs, and service APIs.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router)
    app.include_router(legacy_router)

    @app.get("/", response_model=RootResponse)
    def root() -> RootResponse:
        return RootResponse(
            service="finance-app-backend",
            version=settings.app_version,
            endpoints=[
                "/api/v1/health/live",
                "/api/v1/health/ready",
                "/api/v1/portfolio",
                "/docs",
                "/openapi.json",
            ],
        )

    return app


app = create_app()
