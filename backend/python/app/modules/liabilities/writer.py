"""Atomic internal writer for exact liability balance observations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid5

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountModel
from app.db.models.enums import AccountType, LiabilityBalanceSource
from app.db.models.liabilities import LiabilityBalanceModel
from app.modules.liabilities.validation import (
    LIABILITY_ACCOUNT_TYPES,
    LiabilityBalanceValidationError,
    canonical_currency,
    canonical_external_id,
    canonical_money,
    canonical_nonblank,
    canonical_timestamp,
    canonical_total,
)
from app.modules.liabilities.writer_repository import (
    LiabilityBalanceWriterRepository,
    identity_lock_ids,
)

_STATE_MESSAGE = "Liability balance could not be persisted."
_CONFLICT_MESSAGE = "Liability balance conflicts with persisted state."
_BALANCE_ID_NAMESPACE = UUID("ea19c471-9ff6-59bd-8fe2-33201b0ad13e")


class LiabilityBalanceWriteStateError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(_STATE_MESSAGE)


class LiabilityBalanceWriteConflictError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(_CONFLICT_MESSAGE)


class LiabilityBalanceWriteDisposition(StrEnum):
    created = "created"
    replayed = "replayed"


@dataclass(frozen=True, slots=True)
class WriteLiabilityBalanceCommand:
    account_id: str
    effective_at: datetime
    currency: str
    outstanding_principal: Decimal
    accrued_interest: Decimal
    fees_outstanding: Decimal
    source: LiabilityBalanceSource
    external_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ExpectedLiabilityBalanceRow:
    id: str
    account_id: str
    effective_at: datetime
    currency: str
    outstanding_principal: Decimal
    accrued_interest: Decimal
    fees_outstanding: Decimal
    total_outstanding: Decimal
    source: LiabilityBalanceSource
    external_id: str | None
    created_at: datetime

    def model_values(self) -> dict[str, object]:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "effective_at": self.effective_at,
            "currency": self.currency,
            "outstanding_principal": self.outstanding_principal,
            "accrued_interest": self.accrued_interest,
            "fees_outstanding": self.fees_outstanding,
            "total_outstanding": self.total_outstanding,
            "source": self.source,
            "external_id": self.external_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class LiabilityBalanceWriteResult:
    balance_id: str
    account_id: str
    effective_at: datetime
    currency: str
    total_outstanding: Decimal
    source: LiabilityBalanceSource
    disposition: LiabilityBalanceWriteDisposition


class _Repository(Protocol):
    async def load_account_for_share(self, account_id: str) -> AccountModel | None: ...

    async def acquire_identity_locks(self, lock_ids: tuple[int, ...]) -> None: ...

    async def load_by_timestamp_identity(
        self,
        *,
        account_id: str,
        effective_at: datetime,
        source: LiabilityBalanceSource,
    ) -> LiabilityBalanceModel | None: ...

    async def load_by_external_identity(
        self,
        *,
        account_id: str,
        source: LiabilityBalanceSource,
        external_id: str,
    ) -> LiabilityBalanceModel | None: ...

    async def load_by_id(self, balance_id: str) -> LiabilityBalanceModel | None: ...

    def add(self, balance: LiabilityBalanceModel) -> None: ...

    async def flush(self) -> None: ...

    async def reload(self, balance_id: str) -> LiabilityBalanceModel | None: ...


def _fail() -> LiabilityBalanceWriteStateError:
    return LiabilityBalanceWriteStateError()


def _canonical_or_fail[T](validator: Callable[[object], T], value: object) -> T:
    try:
        return validator(value)
    except LiabilityBalanceValidationError as exc:
        raise _fail() from exc


def _identity_text(value: object) -> str:
    result = _canonical_or_fail(canonical_nonblank, value)
    if "\0" in result:
        raise _fail()
    return result


def deterministic_balance_id(
    *,
    account_id: str,
    effective_at: datetime,
    source: LiabilityBalanceSource,
    external_id: str | None,
) -> str:
    marker = external_id if external_id is not None else "<none>"
    payload = "\0".join(
        (
            "liability-balance",
            account_id,
            effective_at.isoformat(timespec="milliseconds"),
            source.value,
            marker,
        )
    )
    return str(uuid5(_BALANCE_ID_NAMESPACE, payload))


def build_expected_liability_balance(
    command: object,
) -> ExpectedLiabilityBalanceRow:
    if not isinstance(command, WriteLiabilityBalanceCommand):
        raise _fail()
    account_id = _identity_text(command.account_id)
    effective_at = _canonical_or_fail(canonical_timestamp, command.effective_at)
    created_at = _canonical_or_fail(canonical_timestamp, command.created_at)
    currency = _canonical_or_fail(canonical_currency, command.currency)
    principal = _canonical_or_fail(canonical_money, command.outstanding_principal)
    interest = _canonical_or_fail(canonical_money, command.accrued_interest)
    fees = _canonical_or_fail(canonical_money, command.fees_outstanding)
    if min(principal, interest, fees) < 0:
        raise _fail()
    if not isinstance(command.source, LiabilityBalanceSource):
        raise _fail()
    external_id = _canonical_or_fail(canonical_external_id, command.external_id)
    if external_id is not None and "\0" in external_id:
        raise _fail()
    try:
        total = canonical_total(principal, interest, fees)
    except LiabilityBalanceValidationError as exc:
        raise _fail() from exc
    return ExpectedLiabilityBalanceRow(
        id=deterministic_balance_id(
            account_id=account_id,
            effective_at=effective_at,
            source=command.source,
            external_id=external_id,
        ),
        account_id=account_id,
        effective_at=effective_at,
        currency=currency,
        outstanding_principal=principal,
        accrued_interest=interest,
        fees_outstanding=fees,
        total_outstanding=total,
        source=command.source,
        external_id=external_id,
        created_at=created_at,
    )


_PHYSICAL_ATTRIBUTES = (
    "id",
    "account_id",
    "effective_at",
    "currency",
    "outstanding_principal",
    "accrued_interest",
    "fees_outstanding",
    "total_outstanding",
    "source",
    "external_id",
    "created_at",
)


def _matches(
    persisted: object,
    expected: ExpectedLiabilityBalanceRow,
) -> bool:
    if not isinstance(persisted, LiabilityBalanceModel):
        return False
    values = expected.model_values()
    return all(getattr(persisted, name) == values[name] for name in _PHYSICAL_ATTRIBUTES)


def _result(
    expected: ExpectedLiabilityBalanceRow,
    disposition: LiabilityBalanceWriteDisposition,
) -> LiabilityBalanceWriteResult:
    return LiabilityBalanceWriteResult(
        balance_id=expected.id,
        account_id=expected.account_id,
        effective_at=expected.effective_at,
        currency=expected.currency,
        total_outstanding=expected.total_outstanding,
        source=expected.source,
        disposition=disposition,
    )


def _validate_account(
    account: object,
    expected: ExpectedLiabilityBalanceRow,
) -> None:
    if (
        not isinstance(account, AccountModel)
        or account.id != expected.account_id
        or not isinstance(account.type, AccountType)
        or account.type not in LIABILITY_ACCOUNT_TYPES
        or account.is_archived
        or account.archived_at is not None
    ):
        raise _fail()
    try:
        currency = canonical_currency(account.currency)
    except LiabilityBalanceValidationError as exc:
        raise _fail() from exc
    if currency != expected.currency:
        raise _fail()


class LiabilityBalanceWriter:
    """Own one outer transaction and persist or replay one exact observation."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: _Repository | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or LiabilityBalanceWriterRepository(session)

    async def write(
        self,
        command: WriteLiabilityBalanceCommand,
    ) -> LiabilityBalanceWriteResult:
        expected = build_expected_liability_balance(command)
        if self.session.in_transaction():
            raise _fail()
        try:
            async with self.session.begin():
                return await self._write_in_transaction(expected)
        except (LiabilityBalanceWriteStateError, LiabilityBalanceWriteConflictError):
            raise
        except SQLAlchemyError as exc:
            raise _fail() from exc

    async def _write_in_transaction(
        self,
        expected: ExpectedLiabilityBalanceRow,
    ) -> LiabilityBalanceWriteResult:
        account = await self.repository.load_account_for_share(expected.account_id)
        _validate_account(account, expected)
        await self.repository.acquire_identity_locks(
            identity_lock_ids(
                account_id=expected.account_id,
                effective_at=expected.effective_at,
                source=expected.source,
                external_id=expected.external_id,
            )
        )
        by_timestamp = await self.repository.load_by_timestamp_identity(
            account_id=expected.account_id,
            effective_at=expected.effective_at,
            source=expected.source,
        )
        by_external = (
            await self.repository.load_by_external_identity(
                account_id=expected.account_id,
                source=expected.source,
                external_id=expected.external_id,
            )
            if expected.external_id is not None
            else None
        )
        existing = by_timestamp or by_external
        if (
            by_timestamp is not None
            and by_external is not None
            and by_timestamp.id != by_external.id
        ):
            raise LiabilityBalanceWriteConflictError()
        if existing is not None:
            if not _matches(existing, expected):
                raise LiabilityBalanceWriteConflictError()
            return _result(expected, LiabilityBalanceWriteDisposition.replayed)

        id_conflict = await self.repository.load_by_id(expected.id)
        if id_conflict is not None:
            raise LiabilityBalanceWriteConflictError()
        self.repository.add(LiabilityBalanceModel(**expected.model_values()))
        await self.repository.flush()
        persisted = await self.repository.reload(expected.id)
        if not _matches(persisted, expected):
            raise _fail()
        return _result(expected, LiabilityBalanceWriteDisposition.created)
