"""Thin HTTP adapter for an authorized exact dashboard snapshot."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.modules.dashboard_snapshot.api_models import DashboardSnapshotResponse
from app.modules.dashboard_snapshot.authorized_service import (
    AuthorizedDashboardSnapshotService,
)
from app.modules.portfolio_snapshot.multi_account_api_models import (
    ExactPortfolioSnapshotSetRequest,
)
from app.modules.portfolio_snapshot.multi_account_service import (
    AuthorizedMultiAccountPortfolioSnapshotService,
    ExactAccountSnapshotSelection,
    ReadAuthorizedMultiAccountPortfolioSnapshotCommand,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard-snapshot"])


def get_authorized_dashboard_snapshot_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthorizedDashboardSnapshotService:
    return AuthorizedDashboardSnapshotService(
        AuthorizedMultiAccountPortfolioSnapshotService(session)
    )


@router.post(
    "/snapshot",
    response_model=DashboardSnapshotResponse,
    response_model_by_alias=True,
)
async def read_dashboard_snapshot(
    request: ExactPortfolioSnapshotSetRequest,
    principal: CurrentPrincipal,
    service: Annotated[
        AuthorizedDashboardSnapshotService,
        Depends(get_authorized_dashboard_snapshot_service),
    ],
) -> DashboardSnapshotResponse:
    result = await service.read(
        ReadAuthorizedMultiAccountPortfolioSnapshotCommand(
            principal=principal,
            timestamp=request.timestamp,
            granularity=request.granularity,
            currency=request.currency,
            calculation_version=request.calculation_version,
            accounts=tuple(
                ExactAccountSnapshotSelection(
                    account_id=account.account_id,
                    required_snapshot_id=account.snapshot_id,
                )
                for account in request.accounts
            ),
        )
    )
    return DashboardSnapshotResponse.model_validate(
        result.dashboard,
        from_attributes=True,
    )
