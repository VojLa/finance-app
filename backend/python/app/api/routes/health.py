from typing import Literal

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.db.health import check_database


class LivenessResponse(BaseModel):
    status: Literal["ok"]
    service: str


class ReadinessDependencies(BaseModel):
    database: Literal["available", "unavailable"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    dependencies: ReadinessDependencies


router = APIRouter(prefix="/health", tags=["health"])


def _liveness_response() -> LivenessResponse:
    return LivenessResponse(status="ok", service="finance-app-backend")


@router.get("", response_model=LivenessResponse, include_in_schema=False)
def health() -> LivenessResponse:
    """Compatibility alias for the original health endpoint."""
    return _liveness_response()


@router.get("/live", response_model=LivenessResponse)
def liveness() -> LivenessResponse:
    return _liveness_response()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def readiness(request: Request) -> ReadinessResponse | JSONResponse:
    pool = getattr(request.app.state, "db_pool", None)
    if await check_database(pool):
        return ReadinessResponse(
            status="ready",
            dependencies=ReadinessDependencies(database="available"),
        )

    response = ReadinessResponse(
        status="not_ready",
        dependencies=ReadinessDependencies(database="unavailable"),
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=response.model_dump(),
    )
