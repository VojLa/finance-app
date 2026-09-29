import asyncio
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
    portfolioHistoryRuntime: Literal["available", "unavailable", "disabled"]
    scheduledSnapshotRefreshRuntime: Literal["available", "unavailable", "disabled"]


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
    database = getattr(request.app.state, "database", None)
    settings = getattr(request.app.state, "settings", None)
    history_enabled = bool(settings is not None and settings.portfolio_history_runtime_enabled)
    history_tasks = getattr(request.app.state, "portfolio_history_runtime_tasks", ())
    history_available = not history_enabled or (
        isinstance(history_tasks, tuple)
        and len(history_tasks) == 2
        and all(isinstance(task, asyncio.Task) and not task.done() for task in history_tasks)
    )
    scheduled_refresh_enabled = bool(
        settings is not None and settings.scheduled_snapshot_refresh_runner_enabled
    )
    scheduled_refresh_task = getattr(
        request.app.state, "scheduled_snapshot_refresh_runner_task", None
    )
    scheduled_refresh_available = not scheduled_refresh_enabled or (
        isinstance(scheduled_refresh_task, asyncio.Task) and not scheduled_refresh_task.done()
    )
    database_available = await check_database(database)
    history_status: Literal["available", "unavailable", "disabled"] = (
        "available"
        if history_enabled and history_available
        else "unavailable"
        if history_enabled
        else "disabled"
    )
    scheduled_refresh_status: Literal["available", "unavailable", "disabled"] = (
        "available"
        if scheduled_refresh_enabled and scheduled_refresh_available
        else "unavailable"
        if scheduled_refresh_enabled
        else "disabled"
    )
    if database_available and history_available and scheduled_refresh_available:
        return ReadinessResponse(
            status="ready",
            dependencies=ReadinessDependencies(
                database="available",
                portfolioHistoryRuntime=history_status,
                scheduledSnapshotRefreshRuntime=scheduled_refresh_status,
            ),
        )

    response = ReadinessResponse(
        status="not_ready",
        dependencies=ReadinessDependencies(
            database="available" if database_available else "unavailable",
            portfolioHistoryRuntime=history_status,
            scheduledSnapshotRefreshRuntime=scheduled_refresh_status,
        ),
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=response.model_dump(),
    )
