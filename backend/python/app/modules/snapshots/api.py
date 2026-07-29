"""Thin public HTTP adapter for manual account snapshot orchestration."""

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.modules.snapshots.manual_service import (
    Clock,
    ManualAccountSnapshotService,
    RecalculateAccountSnapshotCommand,
    current_snapshot_timestamp,
)
from app.modules.snapshots.models import (
    AccountSnapshotRecalculateRequest,
    AccountSnapshotRecalculateResponse,
)

router = APIRouter(prefix="/accounts/{account_id}/snapshots", tags=["snapshots"])


def get_snapshot_clock() -> Clock:
    return current_snapshot_timestamp


def get_manual_snapshot_service(
    session: AsyncSession = Depends(get_db_session),
    clock: Clock = Depends(get_snapshot_clock),
) -> ManualAccountSnapshotService:
    return ManualAccountSnapshotService(session, clock=clock)


@router.post(
    "/recalculate",
    response_model=AccountSnapshotRecalculateResponse,
    response_model_by_alias=True,
)
async def recalculate_account_snapshot(
    account_id: str,
    principal: CurrentPrincipal,
    request: AccountSnapshotRecalculateRequest | None = Body(default=None),
    service: ManualAccountSnapshotService = Depends(get_manual_snapshot_service),
) -> AccountSnapshotRecalculateResponse:
    result = await service.recalculate(
        RecalculateAccountSnapshotCommand(
            principal=principal,
            account_id=account_id,
            output_currency=None if request is None else request.output_currency,
        )
    )
    return AccountSnapshotRecalculateResponse.model_validate(result, from_attributes=True)
