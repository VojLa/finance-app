from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from uuid import uuid4

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.auth.models import AuthenticatedPrincipal
from app.db.connection import get_db_session
from app.db.models.accounts import AccountInviteModel, AccountMemberModel
from app.db.models.enums import (
    AccountInviteStatus,
    AccountMemberRole,
    AccountRelationType,
)
from app.db.models.users import UserModel
from app.modules.accounts.access import require_account_access
from app.shared.errors import ApplicationError

router = APIRouter(prefix="/accounts", tags=["account invitations"])
OWNER_ONLY = {AccountMemberRole.owner}
INVITABLE_ROLES = {
    AccountMemberRole.admin,
    AccountMemberRole.editor,
    AccountMemberRole.viewer,
}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


class AccountInviteCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: AccountMemberRole = AccountMemberRole.viewer
    expires_in_hours: int = Field(default=72, ge=1, le=168)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @model_validator(mode="after")
    def forbid_owner_role(self) -> AccountInviteCreateRequest:
        if self.role not in INVITABLE_ROLES:
            raise ValueError("The owner role cannot be assigned through an invitation.")
        return self


class AccountInviteAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=32, max_length=512)


class AccountInviteResponse(BaseModel):
    id: str
    account_id: str
    inviter_id: str
    email: str
    role: AccountMemberRole
    status: AccountInviteStatus
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AccountInviteCreatedResponse(AccountInviteResponse):
    token: str


class AccountInviteNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="account_invite_not_found",
            message="The account invitation was not found.",
            status_code=404,
        )


class AccountInviteConflictError(ApplicationError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code=code, message=message, status_code=409)


class AccountInvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_account(self, account_id: str) -> list[AccountInviteModel]:
        result = await self.session.scalars(
            select(AccountInviteModel)
            .where(AccountInviteModel.account_id == account_id)
            .order_by(AccountInviteModel.created_at.asc(), AccountInviteModel.id.asc())
        )
        return list(result.all())

    async def pending_for_email(
        self,
        *,
        account_id: str,
        email: str,
    ) -> AccountInviteModel | None:
        return await self.session.scalar(
            select(AccountInviteModel).where(
                AccountInviteModel.account_id == account_id,
                func.lower(AccountInviteModel.email) == email.lower(),
                AccountInviteModel.status == AccountInviteStatus.pending,
            )
        )

    async def get_for_account(
        self,
        *,
        account_id: str,
        invite_id: str,
    ) -> AccountInviteModel | None:
        return await self.session.scalar(
            select(AccountInviteModel).where(
                AccountInviteModel.id == invite_id,
                AccountInviteModel.account_id == account_id,
            )
        )

    async def get_by_token_hash(self, token_hash: str) -> AccountInviteModel | None:
        return await self.session.scalar(
            select(AccountInviteModel).where(AccountInviteModel.token_hash == token_hash)
        )

    async def user_has_membership(self, *, account_id: str, user_id: str) -> bool:
        membership_id = await self.session.scalar(
            select(AccountMemberModel.id).where(
                AccountMemberModel.account_id == account_id,
                AccountMemberModel.user_id == user_id,
            )
        )
        return membership_id is not None

    async def get_user_email(self, user_id: str) -> str | None:
        return await self.session.scalar(select(UserModel.email).where(UserModel.id == user_id))


class AccountInvitationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = AccountInvitationRepository(session)

    async def create_invite(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        payload: AccountInviteCreateRequest,
    ) -> AccountInviteCreatedResponse:
        await self._require_owner(principal=principal, account_id=account_id)
        existing = await self.repository.pending_for_email(
            account_id=account_id,
            email=str(payload.email),
        )
        if existing is not None:
            raise AccountInviteConflictError(
                "account_invite_pending",
                "A pending invitation already exists for this email address.",
            )

        token = token_urlsafe(32)
        now = _now()
        invite = AccountInviteModel(
            id=str(uuid4()),
            account_id=account_id,
            inviter_id=principal.user_id,
            accepted_by_id=None,
            email=str(payload.email),
            role=payload.role,
            status=AccountInviteStatus.pending,
            token_hash=_token_hash(token),
            expires_at=now + timedelta(hours=payload.expires_in_hours),
            accepted_at=None,
            revoked_at=None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(invite)
        await self._commit()
        return AccountInviteCreatedResponse(**self._response(invite).model_dump(), token=token)

    async def list_invites(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
    ) -> list[AccountInviteResponse]:
        await self._require_owner(principal=principal, account_id=account_id)
        return [self._response(invite) for invite in await self.repository.list_for_account(account_id)]

    async def revoke_invite(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        invite_id: str,
    ) -> None:
        await self._require_owner(principal=principal, account_id=account_id)
        invite = await self.repository.get_for_account(account_id=account_id, invite_id=invite_id)
        if invite is None:
            raise AccountInviteNotFoundError()
        if invite.status is not AccountInviteStatus.pending:
            raise AccountInviteConflictError(
                "account_invite_not_pending",
                "Only a pending invitation can be revoked.",
            )
        now = _now()
        invite.status = AccountInviteStatus.revoked
        invite.revoked_at = now
        invite.updated_at = now
        await self._commit()

    async def accept_invite(
        self,
        *,
        principal: AuthenticatedPrincipal,
        payload: AccountInviteAcceptRequest,
    ) -> AccountMemberModel:
        invite = await self.repository.get_by_token_hash(_token_hash(payload.token))
        if invite is None:
            raise AccountInviteNotFoundError()
        now = _now()
        if invite.status is not AccountInviteStatus.pending:
            raise AccountInviteConflictError(
                "account_invite_not_pending",
                "The invitation is no longer pending.",
            )
        if invite.expires_at <= now:
            invite.status = AccountInviteStatus.expired
            invite.updated_at = now
            await self._commit()
            raise AccountInviteConflictError(
                "account_invite_expired",
                "The invitation has expired.",
            )
        user_email = await self.repository.get_user_email(principal.user_id)
        if user_email is None or user_email.lower() != invite.email.lower():
            raise AccountInviteNotFoundError()
        if await self.repository.user_has_membership(
            account_id=invite.account_id,
            user_id=principal.user_id,
        ):
            raise AccountInviteConflictError(
                "account_membership_exists",
                "The user is already a member of this account.",
            )

        membership = AccountMemberModel(
            id=str(uuid4()),
            account_id=invite.account_id,
            user_id=principal.user_id,
            role=invite.role,
            relation_type=AccountRelationType.collaborator,
            invited_by_id=invite.inviter_id,
            accepted_at=now,
            created_at=now,
            updated_at=now,
        )
        self.session.add(membership)
        invite.status = AccountInviteStatus.accepted
        invite.accepted_by_id = principal.user_id
        invite.accepted_at = now
        invite.updated_at = now
        await self._commit()
        return membership

    async def _require_owner(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
    ) -> None:
        await require_account_access(
            session=self.session,
            principal=principal,
            account_id=account_id,
            allowed_roles=OWNER_ONLY,
        )

    async def _commit(self) -> None:
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    @staticmethod
    def _response(invite: AccountInviteModel) -> AccountInviteResponse:
        return AccountInviteResponse(
            id=invite.id,
            account_id=invite.account_id,
            inviter_id=invite.inviter_id,
            email=invite.email,
            role=invite.role,
            status=invite.status,
            expires_at=invite.expires_at,
            accepted_at=invite.accepted_at,
            revoked_at=invite.revoked_at,
            created_at=invite.created_at,
            updated_at=invite.updated_at,
        )


@router.post(
    "/{account_id}/invites",
    response_model=AccountInviteCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_account_invite(
    account_id: str,
    payload: AccountInviteCreateRequest,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> AccountInviteCreatedResponse:
    return await AccountInvitationService(session).create_invite(
        principal=principal,
        account_id=account_id,
        payload=payload,
    )


@router.get("/{account_id}/invites", response_model=list[AccountInviteResponse])
async def list_account_invites(
    account_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> list[AccountInviteResponse]:
    return await AccountInvitationService(session).list_invites(
        principal=principal,
        account_id=account_id,
    )


@router.delete(
    "/{account_id}/invites/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def revoke_account_invite(
    account_id: str,
    invite_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    await AccountInvitationService(session).revoke_invite(
        principal=principal,
        account_id=account_id,
        invite_id=invite_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invites/accept", status_code=status.HTTP_201_CREATED)
async def accept_account_invite(
    payload: AccountInviteAcceptRequest,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    membership = await AccountInvitationService(session).accept_invite(
        principal=principal,
        payload=payload,
    )
    return {"account_id": membership.account_id, "member_id": membership.id}
