"""Atomic internal writer for exact physical account snapshots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountModel
from app.db.models.common import TIMESTAMP
from app.db.models.enums import AccountType, SnapshotGranularity, SnapshotSource
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.modules.snapshots.evidence_service import (
    AccountSnapshotEvidenceService,
    BuildAccountSnapshotEvidenceCommand,
    CompleteAccountSnapshotEvidence,
)
from app.modules.snapshots.financial_metrics import (
    AccountSnapshotEvidenceStateError,
    canonical_currency,
    canonical_timestamp,
)
from app.modules.snapshots.persistence_projection import (
    AccountSnapshotPersistenceMetadata,
    AccountSnapshotPersistenceProjectionError,
    ExpectedAccountSnapshotItemRow,
    ExpectedAccountSnapshotPersistence,
    ExpectedAccountSnapshotRow,
    build_account_snapshot_persistence_projection,
)
from app.modules.snapshots.writer_repository import AccountSnapshotWriterRepository

_STATE_MESSAGE = "Account snapshot could not be persisted."
_CONFLICT_MESSAGE = "Account snapshot conflicts with persisted state."
_POSTGRES_INTEGER_MAX = 2_147_483_647
_LIABILITY_ACCOUNT_TYPES = {
    AccountType.credit_card,
    AccountType.loan,
    AccountType.mortgage,
}


class AccountSnapshotWriteStateError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(_STATE_MESSAGE)


class AccountSnapshotWriteConflictError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(_CONFLICT_MESSAGE)


class AccountSnapshotWriteDisposition(StrEnum):
    created = "created"
    replayed = "replayed"


@dataclass(frozen=True, slots=True)
class WriteAccountSnapshotCommand:
    account_id: str
    snapshot_timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    calculation_version: int
    calculated_at: datetime
    created_at: datetime
    is_recalculated: bool
    output_currency: str | None = None


@dataclass(frozen=True, slots=True)
class AccountSnapshotWriteResult:
    snapshot_id: str
    account_id: str
    disposition: AccountSnapshotWriteDisposition
    item_count: int
    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str


class _EvidenceBuilder(Protocol):
    async def build(
        self,
        command: BuildAccountSnapshotEvidenceCommand,
    ) -> CompleteAccountSnapshotEvidence: ...


type _ProjectionBuilder = Callable[
    [CompleteAccountSnapshotEvidence, AccountSnapshotPersistenceMetadata],
    ExpectedAccountSnapshotPersistence,
]


def _fail() -> AccountSnapshotWriteStateError:
    return AccountSnapshotWriteStateError()


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _timestamp(value: object) -> datetime:
    try:
        result = canonical_timestamp(value)
    except AccountSnapshotEvidenceStateError as exc:
        raise _fail() from exc
    precision = TIMESTAMP.precision
    if precision is None or result.microsecond % (10 ** (6 - precision)):
        raise _fail()
    return result


def _validate_command(command: object) -> WriteAccountSnapshotCommand:
    if not isinstance(command, WriteAccountSnapshotCommand):
        raise _fail()
    account_id = _nonblank(command.account_id)
    snapshot_timestamp = _timestamp(command.snapshot_timestamp)
    calculated_at = _timestamp(command.calculated_at)
    created_at = _timestamp(command.created_at)
    output_currency: str | None = None
    if command.output_currency is not None:
        try:
            output_currency = canonical_currency(command.output_currency)
        except AccountSnapshotEvidenceStateError as exc:
            raise _fail() from exc
    if (
        not isinstance(command.granularity, SnapshotGranularity)
        or not isinstance(command.source, SnapshotSource)
        or not isinstance(command.calculation_version, int)
        or isinstance(command.calculation_version, bool)
        or not 0 < command.calculation_version <= _POSTGRES_INTEGER_MAX
        or not isinstance(command.is_recalculated, bool)
    ):
        raise _fail()
    return WriteAccountSnapshotCommand(
        account_id=account_id,
        snapshot_timestamp=snapshot_timestamp,
        granularity=command.granularity,
        source=command.source,
        calculation_version=command.calculation_version,
        calculated_at=calculated_at,
        created_at=created_at,
        is_recalculated=command.is_recalculated,
        output_currency=output_currency,
    )


_SNAPSHOT_ATTRIBUTES = (
    "id",
    "account_id",
    "timestamp",
    "granularity",
    "source",
    "currency",
    "cash_value",
    "investment_value",
    "investment_cost_basis",
    "liabilities_value",
    "total_value",
    "is_recalculated",
    "calculated_at",
    "calculation_version",
    "created_at",
    "net_deposits_value",
    "realized_pnl_value",
    "unrealized_pnl_value",
    "fees_value",
    "taxes_value",
    "cash_value_by_currency",
    "investment_value_by_currency",
    "investment_cost_basis_by_currency",
    "net_deposits_by_currency",
    "realized_pnl_by_currency",
    "unrealized_pnl_by_currency",
    "fees_by_currency",
    "taxes_by_currency",
    "exchange_rates",
)

_ITEM_ATTRIBUTES = (
    "id",
    "snapshot_id",
    "asset_id",
    "listing_id",
    "symbol",
    "quantity",
    "price_per_unit",
    "price_currency",
    "price_source",
    "price_timestamp",
    "value",
    "cost_basis",
    "cost_currency",
    "allocation_pct",
    "created_at",
    "native_value",
    "value_currency",
    "native_cost_basis",
    "native_cost_currency",
)


def _matches_snapshot(
    persisted: AccountSnapshotModel,
    expected: ExpectedAccountSnapshotRow,
) -> bool:
    values = expected.model_values()
    return all(getattr(persisted, name) == values[name] for name in _SNAPSHOT_ATTRIBUTES)


def _matches_items(
    persisted: tuple[AccountSnapshotItemModel, ...],
    expected: tuple[ExpectedAccountSnapshotItemRow, ...],
) -> bool:
    ordered = tuple(sorted(persisted, key=lambda item: (item.listing_id, item.id)))
    expected_ordered = tuple(sorted(expected, key=lambda item: (item.listing_id, item.id)))
    if len(ordered) != len(expected_ordered):
        return False
    for actual, plan in zip(ordered, expected_ordered, strict=True):
        values = plan.model_values()
        if any(getattr(actual, name) != values[name] for name in _ITEM_ATTRIBUTES):
            return False
    return True


def _result(
    projection: ExpectedAccountSnapshotPersistence,
    disposition: AccountSnapshotWriteDisposition,
) -> AccountSnapshotWriteResult:
    snapshot = projection.snapshot
    return AccountSnapshotWriteResult(
        snapshot_id=snapshot.id,
        account_id=snapshot.account_id,
        disposition=disposition,
        item_count=len(projection.items),
        timestamp=snapshot.timestamp,
        granularity=snapshot.granularity,
        currency=snapshot.currency,
    )


def _validate_projection_identity(
    projection: ExpectedAccountSnapshotPersistence,
    *,
    command: WriteAccountSnapshotCommand,
    output_currency: str,
) -> None:
    snapshot = projection.snapshot
    if (
        snapshot.account_id != command.account_id
        or snapshot.timestamp != command.snapshot_timestamp
        or snapshot.granularity is not command.granularity
        or snapshot.currency != output_currency
        or snapshot.source is not command.source
        or snapshot.calculation_version != command.calculation_version
        or snapshot.calculated_at != command.calculated_at
        or snapshot.created_at != command.created_at
        or snapshot.is_recalculated is not command.is_recalculated
    ):
        raise _fail()


class AccountSnapshotWriter:
    """Persist one primary snapshot and its account-currency companion atomically."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: AccountSnapshotWriterRepository | None = None,
        evidence_service: _EvidenceBuilder | None = None,
        projection_builder: _ProjectionBuilder = (build_account_snapshot_persistence_projection),
    ) -> None:
        self.session = session
        self.repository = repository or AccountSnapshotWriterRepository(session)
        self.evidence_service = evidence_service or AccountSnapshotEvidenceService(session)
        self.projection_builder = projection_builder

    async def write(
        self,
        command: WriteAccountSnapshotCommand,
    ) -> AccountSnapshotWriteResult:
        canonical = _validate_command(command)
        if self.session.in_transaction():
            raise _fail()
        try:
            async with self.session.begin():
                return await self._write_in_transaction(canonical)
        except (
            AccountSnapshotWriteStateError,
            AccountSnapshotWriteConflictError,
            AccountSnapshotEvidenceStateError,
            AccountSnapshotPersistenceProjectionError,
        ):
            raise
        except SQLAlchemyError as exc:
            raise _fail() from exc

    async def _write_in_transaction(
        self,
        command: WriteAccountSnapshotCommand,
    ) -> AccountSnapshotWriteResult:
        account = await self.repository.load_account_for_share(command.account_id)
        if account is None:
            raise _fail()
        account_currency, account_type = _validate_account(account, command.account_id)
        output_currency = (
            account_currency if command.output_currency is None else command.output_currency
        )
        currencies = tuple(sorted({output_currency, account_currency}))
        for currency in currencies:
            await self.repository.acquire_snapshot_lock(
                account_id=command.account_id,
                timestamp=command.snapshot_timestamp,
                currency=currency,
                granularity=command.granularity,
            )
        if account_type in _LIABILITY_ACCOUNT_TYPES:
            await self.repository.lock_liability_evidence_table()
            if len(currencies) > 1:
                await self.repository.lock_market_evidence_tables()
        else:
            await self.repository.lock_canonical_evidence(command.account_id)
            await self.repository.lock_market_evidence_tables()

        projections: dict[str, ExpectedAccountSnapshotPersistence] = {}
        for currency in currencies:
            evidence = await self.evidence_service.build(
                BuildAccountSnapshotEvidenceCommand(
                    account_id=command.account_id,
                    snapshot_timestamp=command.snapshot_timestamp,
                    granularity=command.granularity,
                    source=command.source,
                    calculation_version=command.calculation_version,
                    output_currency=currency,
                )
            )
            projection = self.projection_builder(
                evidence,
                AccountSnapshotPersistenceMetadata(
                    calculated_at=command.calculated_at,
                    created_at=command.created_at,
                    is_recalculated=command.is_recalculated,
                ),
            )
            _validate_projection_identity(
                projection,
                command=command,
                output_currency=currency,
            )
            projections[currency] = projection

        dispositions: dict[str, AccountSnapshotWriteDisposition] = {}
        for currency in currencies:
            projection = projections[currency]
            existing = await self.repository.load_existing_snapshot(
                account_id=command.account_id,
                timestamp=command.snapshot_timestamp,
                currency=currency,
                granularity=command.granularity,
            )
            if existing is not None:
                items = await self.repository.load_snapshot_items(existing.id)
                if not _matches_snapshot(existing, projection.snapshot) or not _matches_items(
                    items, projection.items
                ):
                    raise AccountSnapshotWriteConflictError()
                dispositions[currency] = AccountSnapshotWriteDisposition.replayed
                continue
            id_conflict = await self.repository.load_snapshot_by_id(projection.snapshot.id)
            if id_conflict is not None:
                raise AccountSnapshotWriteConflictError()

        for currency in currencies:
            if currency in dispositions:
                continue
            projection = projections[currency]
            self.repository.add_snapshot(AccountSnapshotModel(**projection.snapshot.model_values()))
            await self.repository.flush()
            self.repository.add_items(
                tuple(AccountSnapshotItemModel(**item.model_values()) for item in projection.items)
            )
            await self.repository.flush()
            persisted = await self.repository.reload_snapshot(projection.snapshot.id)
            persisted_items = await self.repository.reload_snapshot_items(projection.snapshot.id)
            if (
                persisted is None
                or not _matches_snapshot(persisted, projection.snapshot)
                or not _matches_items(persisted_items, projection.items)
            ):
                raise _fail()
            dispositions[currency] = AccountSnapshotWriteDisposition.created

        return _result(projections[output_currency], dispositions[output_currency])


def _validate_account(account: AccountModel, account_id: str) -> tuple[str, AccountType]:
    if (
        account.id != account_id
        or account.is_archived
        or account.archived_at is not None
        or not isinstance(account.type, AccountType)
    ):
        raise _fail()
    try:
        return canonical_currency(account.currency), account.type
    except AccountSnapshotEvidenceStateError as exc:
        raise _fail() from exc
