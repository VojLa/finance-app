from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.modules.accounts.invitations import router as invitation_router
from app.modules.accounts.models import (
    AccountCreateRequest,
    AccountMemberResponse,
    AccountMemberRoleUpdateRequest,
    AccountResponse,
    AccountUpdateRequest,
)
from app.modules.accounts.service import AccountService

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountResponse])
async def list_accounts(
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> list[AccountResponse]:
    return await AccountService(session).list_accounts(principal)


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    payload: AccountCreateRequest,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> AccountResponse:
    return await AccountService(session).create_account(principal=principal, payload=payload)


@router.patch("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: str,
    payload: AccountUpdateRequest,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> AccountResponse:
    return await AccountService(session).update_account(
        principal=principal,
        account_id=account_id,
        payload=payload,
    )


@router.get("/{account_id}/members", response_model=list[AccountMemberResponse])
async def list_account_members(
    account_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> list[AccountMemberResponse]:
    return await AccountService(session).list_members(
        principal=principal,
        account_id=account_id,
    )


@router.patch("/{account_id}/members/{member_id}", response_model=AccountMemberResponse)
async def update_account_member_role(
    account_id: str,
    member_id: str,
    payload: AccountMemberRoleUpdateRequest,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> AccountMemberResponse:
    return await AccountService(session).update_member_role(
        principal=principal,
        account_id=account_id,
        member_id=member_id,
        payload=payload,
    )


@router.delete(
    "/{account_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def remove_account_member(
    account_id: str,
    member_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    await AccountService(session).remove_member(
        principal=principal,
        account_id=account_id,
        member_id=member_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{account_id}/archive", response_model=AccountResponse)
async def archive_account(
    account_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> AccountResponse:
    return await AccountService(session).archive_account(
        principal=principal,
        account_id=account_id,
    )


@router.post("/{account_id}/restore", response_model=AccountResponse)
async def restore_account(
    account_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> AccountResponse:
    return await AccountService(session).restore_account(
        principal=principal,
        account_id=account_id,
    )


router.include_router(invitation_router)
