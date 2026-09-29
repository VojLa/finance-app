"""Thin HTTP adapter for manual liability observations."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.modules.liabilities.manual_models import (
    ManualLiabilityBalanceCreateRequest,
    ManualLiabilityBalanceCreateResponse,
)
from app.modules.liabilities.manual_service import (
    CreateManualLiabilityBalanceCommand,
    ManualLiabilityBalanceService,
)

router = APIRouter(prefix="/accounts/{account_id}/liability-balances", tags=["liabilities"])


@router.post(
    "",
    response_model=ManualLiabilityBalanceCreateResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
)
async def create_manual_liability_balance(
    account_id: str,
    payload: ManualLiabilityBalanceCreateRequest,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> ManualLiabilityBalanceCreateResponse:
    result = await ManualLiabilityBalanceService(session).create(
        CreateManualLiabilityBalanceCommand(
            principal=principal,
            account_id=account_id,
            effective_at=payload.effective_at,
            currency=payload.currency,
            outstanding_principal=payload.outstanding_principal,
            accrued_interest=payload.accrued_interest,
            fees_outstanding=payload.fees_outstanding,
        )
    )
    return ManualLiabilityBalanceCreateResponse.model_validate(result, from_attributes=True)
