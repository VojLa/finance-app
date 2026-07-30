"""Thin HTTP adapter for an authorized exact portfolio snapshot read."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.modules.portfolio_snapshot.api_models import PortfolioSnapshotResponse
from app.modules.portfolio_snapshot.authorized_service import (
    AuthorizedPortfolioSnapshotService,
    ReadAuthorizedPortfolioSnapshotCommand,
)
from app.modules.portfolio_snapshot.models import SnapshotGranularity

router = APIRouter(prefix="/portfolio", tags=["portfolio-snapshot"])


def get_authorized_portfolio_snapshot_service(
    session: AsyncSession = Depends(get_db_session),
) -> AuthorizedPortfolioSnapshotService:
    return AuthorizedPortfolioSnapshotService(session)


@router.get(
    "/accounts/{account_id}/snapshot",
    response_model=PortfolioSnapshotResponse,
    response_model_by_alias=True,
)
async def read_portfolio_snapshot(
    account_id: str,
    principal: CurrentPrincipal,
    timestamp: datetime,
    granularity: SnapshotGranularity,
    currency: str,
    calculation_version: Annotated[int, Query(alias="calculationVersion")],
    snapshot_id: Annotated[str | None, Query(alias="snapshotId")] = None,
    service: AuthorizedPortfolioSnapshotService = Depends(
        get_authorized_portfolio_snapshot_service
    ),
) -> PortfolioSnapshotResponse:
    result = await service.read(
        ReadAuthorizedPortfolioSnapshotCommand(
            principal=principal,
            account_id=account_id,
            timestamp=timestamp,
            granularity=granularity,
            currency=currency,
            calculation_version=calculation_version,
            required_snapshot_id=snapshot_id,
        )
    )
    return PortfolioSnapshotResponse.model_validate(result.view, from_attributes=True)
