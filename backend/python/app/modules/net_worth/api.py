"""Thin HTTP adapter for authenticated manual net-worth recalculation."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.modules.net_worth.manual_service import (
    Clock,
    ManualNetWorthSnapshotService,
    RecalculateNetWorthSnapshotCommand,
    current_net_worth_timestamp,
)
from app.modules.net_worth.models import NetWorthSnapshotRecalculateResponse

router = APIRouter(prefix="/net-worth/snapshots", tags=["net-worth"])


def get_net_worth_clock() -> Clock:
    return current_net_worth_timestamp


def get_manual_net_worth_snapshot_service(
    session: AsyncSession = Depends(get_db_session),
    clock: Clock = Depends(get_net_worth_clock),
) -> ManualNetWorthSnapshotService:
    return ManualNetWorthSnapshotService(session, clock=clock)


@router.post(
    "/recalculate",
    response_model=NetWorthSnapshotRecalculateResponse,
    response_model_by_alias=True,
)
async def recalculate_net_worth_snapshot(
    principal: CurrentPrincipal,
    service: ManualNetWorthSnapshotService = Depends(get_manual_net_worth_snapshot_service),
) -> NetWorthSnapshotRecalculateResponse:
    result = await service.recalculate(RecalculateNetWorthSnapshotCommand(principal=principal))
    return NetWorthSnapshotRecalculateResponse.model_validate(
        result,
        from_attributes=True,
    )
