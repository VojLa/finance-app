"""Authorized orchestration for exact manually entered liability balances."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import AccountMemberRole, LiabilityBalanceSource
from app.modules.accounts.access import (
    AccountAccessDeniedError,
    AccountNotFoundError,
    require_account_access,
)
from app.modules.liabilities.writer import (
    LiabilityBalanceWriteConflictError,
    LiabilityBalanceWriter,
    LiabilityBalanceWriteResult,
    LiabilityBalanceWriteStateError,
    WriteLiabilityBalanceCommand,
)
from app.shared.errors import ApplicationError

WRITE_ROLES = {
    AccountMemberRole.owner,
    AccountMemberRole.admin,
    AccountMemberRole.editor,
}
Clock = Callable[[], datetime]


class ManualLiabilityBalanceUnavailableError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="manual_liability_balance_unavailable",
            message="Liability balance cannot be recorded for the current account data.",
            status_code=409,
        )


class ManualLiabilityBalanceConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="manual_liability_balance_conflict",
            message="Liability balance conflicts with an existing observation.",
            status_code=409,
        )


@dataclass(frozen=True, slots=True)
class CreateManualLiabilityBalanceCommand:
    principal: AuthenticatedPrincipal
    account_id: str
    effective_at: datetime
    currency: str
    outstanding_principal: Decimal
    accrued_interest: Decimal
    fees_outstanding: Decimal


@dataclass(frozen=True, slots=True)
class CreateManualLiabilityBalanceResult:
    balance_id: str
    account_id: str
    effective_at: datetime
    currency: str
    total_outstanding: Decimal
    source: Literal["manual"]
    status: Literal["created", "replayed"]


class _Writer(Protocol):
    async def write(self, command: WriteLiabilityBalanceCommand) -> LiabilityBalanceWriteResult: ...


type WriterFactory = Callable[[AsyncSession], _Writer]


def current_liability_balance_timestamp() -> datetime:
    current = datetime.now(UTC).replace(tzinfo=None)
    return current.replace(microsecond=(current.microsecond // 1_000) * 1_000)


class ManualLiabilityBalanceService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Clock = current_liability_balance_timestamp,
        writer_factory: WriterFactory = LiabilityBalanceWriter,
    ) -> None:
        self.session = session
        self.clock = clock
        self.writer_factory = writer_factory

    async def create(self, command: object) -> CreateManualLiabilityBalanceResult:
        if not isinstance(command, CreateManualLiabilityBalanceCommand):
            await self._close_authorization_transaction()
            raise ManualLiabilityBalanceUnavailableError()
        if (
            not isinstance(command.account_id, str)
            or not command.account_id
            or command.account_id != command.account_id.strip()
        ):
            await self._close_authorization_transaction()
            raise AccountNotFoundError()

        try:
            await require_account_access(
                session=self.session,
                principal=command.principal,
                account_id=command.account_id,
                allowed_roles=WRITE_ROLES,
            )
        except (AccountNotFoundError, AccountAccessDeniedError) as exc:
            await self._close_authorization_transaction()
            # Do not disclose whether an otherwise visible account rejected the
            # caller only because of their role.
            raise AccountNotFoundError() from exc
        except Exception:
            await self._close_authorization_transaction()
            raise

        # Access resolution starts a read transaction.  LiabilityBalanceWriter
        # intentionally owns the only write transaction and revalidates the
        # locked account, covering archive/type/currency changes after auth.
        await self.session.commit()
        if self.session.in_transaction():
            raise RuntimeError("Liability writer requires an idle database session.")

        try:
            result = await self.writer_factory(self.session).write(
                WriteLiabilityBalanceCommand(
                    account_id=command.account_id,
                    effective_at=command.effective_at,
                    currency=command.currency,
                    outstanding_principal=command.outstanding_principal,
                    accrued_interest=command.accrued_interest,
                    fees_outstanding=command.fees_outstanding,
                    source=LiabilityBalanceSource.manual,
                    external_id=None,
                    created_at=self.clock(),
                )
            )
        except LiabilityBalanceWriteConflictError as exc:
            raise ManualLiabilityBalanceConflictError() from exc
        except LiabilityBalanceWriteStateError as exc:
            raise ManualLiabilityBalanceUnavailableError() from exc

        if result.source is not LiabilityBalanceSource.manual:
            raise ManualLiabilityBalanceUnavailableError()
        return CreateManualLiabilityBalanceResult(
            balance_id=result.balance_id,
            account_id=result.account_id,
            effective_at=result.effective_at,
            currency=result.currency,
            total_outstanding=result.total_outstanding,
            source="manual",
            status=result.disposition.value,
        )

    async def _close_authorization_transaction(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
