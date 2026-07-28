"""Read-only latest-as-of canonical liability balance selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountModel
from app.db.models.common import MONEY, TIMESTAMP
from app.db.models.enums import AccountType, LiabilityBalanceSource
from app.db.models.liabilities import LiabilityBalanceModel
from app.modules.liabilities.repository import LiabilityBalanceEvidenceRepository

_ERROR_MESSAGE = "Liability balance evidence is unavailable."
_LIABILITY_ACCOUNT_TYPES = {
    AccountType.credit_card,
    AccountType.loan,
    AccountType.mortgage,
}


class LiabilityBalanceEvidenceStateError(ValueError):
    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


@dataclass(frozen=True, slots=True)
class SelectLiabilityBalanceCommand:
    account_id: str
    snapshot_timestamp: datetime


@dataclass(frozen=True, slots=True)
class LiabilityBalanceEvidence:
    balance_id: str
    account_id: str
    effective_at: datetime
    currency: str
    outstanding_principal: Decimal
    accrued_interest: Decimal
    fees_outstanding: Decimal
    total_outstanding: Decimal
    source: LiabilityBalanceSource


class _Repository(Protocol):
    async def load_account(self, account_id: str) -> AccountModel | None: ...

    async def load_eligible_balances(
        self,
        account_id: str,
        *,
        through: datetime,
    ) -> tuple[LiabilityBalanceModel, ...]: ...


def _fail() -> LiabilityBalanceEvidenceStateError:
    return LiabilityBalanceEvidenceStateError()


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _timestamp(value: object) -> datetime:
    precision = TIMESTAMP.precision
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or precision is None
        or not 0 <= precision <= 6
        or value.microsecond % (10 ** (6 - precision))
    ):
        raise _fail()
    return value


def _currency(value: object) -> str:
    currency = _nonblank(value)
    if len(currency) != 3 or currency != currency.upper() or not currency.isalpha():
        raise _fail()
    return currency


def _money(value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise _fail()
    precision, scale = MONEY.precision, MONEY.scale
    if precision is None or scale is None:
        raise RuntimeError("Canonical MONEY must define precision and scale.")
    try:
        with localcontext() as context:
            context.prec = max(precision * 4, 84)
            scaled = value.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation as exc:
        raise _fail() from exc
    if value != scaled or abs(value) >= Decimal(10) ** (precision - scale):
        raise _fail()
    return value


def _total(principal: Decimal, interest: Decimal, fees: Decimal) -> Decimal:
    try:
        with localcontext() as context:
            context.prec = 84
            result = principal + interest + fees
    except (InvalidOperation, OverflowError) as exc:
        raise _fail() from exc
    return _money(result)


def _validate_account(account: object, account_id: str) -> AccountModel:
    if (
        not isinstance(account, AccountModel)
        or _nonblank(account.id) != account_id
        or not isinstance(account.type, AccountType)
        or account.type not in _LIABILITY_ACCOUNT_TYPES
        or account.is_archived
        or account.archived_at is not None
    ):
        raise _fail()
    _currency(account.currency)
    return account


def _validate_balance(
    row: object,
    *,
    account: AccountModel,
    snapshot_timestamp: datetime,
) -> LiabilityBalanceEvidence:
    if not isinstance(row, LiabilityBalanceModel):
        raise _fail()
    balance_id = _nonblank(row.id)
    if _nonblank(row.account_id) != account.id:
        raise _fail()
    effective_at = _timestamp(row.effective_at)
    _timestamp(row.created_at)
    if effective_at > snapshot_timestamp:
        raise _fail()
    currency = _currency(row.currency)
    if currency != account.currency:
        raise _fail()
    principal = _money(row.outstanding_principal)
    interest = _money(row.accrued_interest)
    fees = _money(row.fees_outstanding)
    total = _money(row.total_outstanding)
    if min(principal, interest, fees, total) < 0 or _total(principal, interest, fees) != total:
        raise _fail()
    if not isinstance(row.source, LiabilityBalanceSource):
        raise _fail()
    if row.external_id is not None and (
        not isinstance(row.external_id, str)
        or not row.external_id
        or row.external_id != row.external_id.strip()
    ):
        raise _fail()
    return LiabilityBalanceEvidence(
        balance_id=balance_id,
        account_id=account.id,
        effective_at=effective_at,
        currency=currency,
        outstanding_principal=principal,
        accrued_interest=interest,
        fees_outstanding=fees,
        total_outstanding=total,
        source=row.source,
    )


class LiabilityBalanceEvidenceService:
    """Select exact liability evidence without owning the caller transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: _Repository | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or LiabilityBalanceEvidenceRepository(session)

    async def select(
        self,
        command: SelectLiabilityBalanceCommand,
    ) -> LiabilityBalanceEvidence:
        if not isinstance(command, SelectLiabilityBalanceCommand):
            raise _fail()
        account_id = _nonblank(command.account_id)
        snapshot_timestamp = _timestamp(command.snapshot_timestamp)
        account = _validate_account(
            await self.repository.load_account(account_id),
            account_id,
        )
        rows = await self.repository.load_eligible_balances(
            account_id,
            through=snapshot_timestamp,
        )
        if not rows:
            raise _fail()
        identities: set[str] = set()
        for row in rows:
            if not isinstance(row, LiabilityBalanceModel) or row.id in identities:
                raise _fail()
            identities.add(row.id)
            if row.account_id != account_id or _timestamp(row.effective_at) > snapshot_timestamp:
                raise _fail()
        latest_at = max(row.effective_at for row in rows)
        latest = tuple(row for row in rows if row.effective_at == latest_at)
        if len(latest) != 1:
            raise _fail()
        return _validate_balance(
            latest[0],
            account=account,
            snapshot_timestamp=snapshot_timestamp,
        )
