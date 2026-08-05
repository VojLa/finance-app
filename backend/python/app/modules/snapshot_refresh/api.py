"""Thin HTTP adapter for coordinated manual snapshot refresh."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal, get_request_settings
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.modules.snapshot_refresh.manual_service import (
    Clock,
    ManualUserSnapshotRefreshService,
    RecalculateUserSnapshotRefreshCommand,
    current_user_snapshot_refresh_timestamp,
)
from app.modules.snapshot_refresh.market_backed_service import (
    MarketBackedSnapshotRefreshService,
)
from app.modules.snapshot_refresh.models import (
    UserSnapshotRefreshRecalculateResponse,
)

router = APIRouter(prefix="/snapshot-refresh", tags=["snapshot-refresh"])


def get_user_snapshot_refresh_clock() -> Clock:
    return current_user_snapshot_refresh_timestamp


def get_market_backed_snapshot_refresh_service(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_request_settings),
) -> MarketBackedSnapshotRefreshService:
    return MarketBackedSnapshotRefreshService(session, settings)


def get_manual_user_snapshot_refresh_service(
    session: AsyncSession = Depends(get_db_session),
    clock: Clock = Depends(get_user_snapshot_refresh_clock),
    market_backed_service: MarketBackedSnapshotRefreshService = Depends(
        get_market_backed_snapshot_refresh_service
    ),
) -> ManualUserSnapshotRefreshService:
    return ManualUserSnapshotRefreshService(
        session,
        clock=clock,
        market_backed_service=market_backed_service,
    )


@router.post(
    "/recalculate",
    response_model=UserSnapshotRefreshRecalculateResponse,
    response_model_by_alias=True,
)
async def recalculate_user_snapshot_refresh(
    principal: CurrentPrincipal,
    service: ManualUserSnapshotRefreshService = Depends(get_manual_user_snapshot_refresh_service),
) -> UserSnapshotRefreshRecalculateResponse:
    result = await service.recalculate(RecalculateUserSnapshotRefreshCommand(principal=principal))
    return UserSnapshotRefreshRecalculateResponse.model_validate(
        result,
        from_attributes=True,
    )
