from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.modules.investments.models import (
    ManualInvestmentCreateRequest,
    ManualInvestmentCreateResponse,
    SymbolDetailResponse,
)
from app.modules.investments.service import InvestmentService
from app.modules.market_data.source_policy import market_evidence_source_policy_from_settings
from app.modules.snapshot_refresh.api import get_manual_user_snapshot_refresh_service
from app.modules.snapshot_refresh.manual_service import ManualUserSnapshotRefreshService
from app.shared.errors import ErrorResponse

router = APIRouter(prefix="/investments", tags=["investments"])


@router.post(
    "/manual",
    response_model=ManualInvestmentCreateResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def create_manual_investment(
    payload: ManualInvestmentCreateRequest,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    snapshot_service: Annotated[
        ManualUserSnapshotRefreshService,
        Depends(get_manual_user_snapshot_refresh_service),
    ],
) -> ManualInvestmentCreateResponse:
    return await InvestmentService(session, snapshot_service=snapshot_service).create_manual(
        principal=principal,
        payload=payload,
    )


@router.get(
    "/symbols/{symbol}",
    response_model=SymbolDetailResponse,
    response_model_by_alias=True,
    responses={409: {"model": ErrorResponse}},
)
async def read_symbol_detail(
    symbol: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> SymbolDetailResponse:
    settings: Settings = request.app.state.settings
    return await InvestmentService(session).symbol_detail(
        principal=principal,
        symbol=symbol,
        source_policy=market_evidence_source_policy_from_settings(settings),
    )
