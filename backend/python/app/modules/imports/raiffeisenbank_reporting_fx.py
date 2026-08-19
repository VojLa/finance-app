"""Acquire and atomically persist direct event-date RB reporting FX evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.background_jobs import BackgroundJobModel, ImportJobBatchModel
from app.db.models.enums import BackgroundJobStatus, ExchangeRateSource, ImportSource
from app.db.models.imports import ImportBatchModel
from app.db.models.prices import ExchangeRateModel
from app.db.models.transactions import TransactionModel, TransactionReportingEvidenceModel
from app.modules.fx.models import ExchangeRateObservation
from app.modules.fx.validation import (
    ExchangeRateObservationValidationError,
    validate_exchange_rate_observation,
)
from app.modules.imports.raiffeisenbank_reporting_fx_repository import (
    RaiffeisenbankReportingFxRepository,
    reporting_fx_job_lock_scope,
    reporting_fx_rate_lock_scope,
)
from app.modules.market_data.models import ExchangeRateRequirement, MarketEvidenceStateError
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
    validate_market_evidence_policy,
)
from app.modules.market_data.providers import (
    BatchExchangeRateProvider,
    ExchangeRateProviderRegistry,
)
from app.modules.market_data.source_policy import (
    MarketEvidenceSourcePolicy,
    validate_market_evidence_source_policy,
)
from app.modules.market_data.writer import exchange_rate_id

REPORTING_FX_CALCULATION_VERSION = 1
_MONEY_QUANTUM = Decimal("0.000001")
_MAX_MONEY_INTEGER_DIGITS = 12
_MAX_TRANSACTION_ATTEMPTS = 3
_RETRYABLE_SQLSTATES = {"40001", "40P01", "23505"}


class RaiffeisenbankReportingFxStateError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Raiffeisenbank reporting FX evidence is unavailable.")


class RaiffeisenbankReportingFxConflictError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Raiffeisenbank reporting FX evidence conflicts with durable state.")


@dataclass(frozen=True, slots=True)
class AcquireRaiffeisenbankReportingFxCommand:
    job_id: str
    user_id: str
    reporting_currency: str
    canonical_transaction_ids: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RaiffeisenbankReportingFxTransaction:
    transaction_id: str
    batch_id: str
    account_id: str
    source_amount: Decimal
    source_currency: str
    source_event_time: datetime
    existing_reporting_amount: Decimal | None
    existing_reporting_currency: str | None


@dataclass(frozen=True, slots=True)
class RaiffeisenbankReportingFxPlan:
    job_id: str
    user_id: str
    reporting_currency: str
    transactions: tuple[RaiffeisenbankReportingFxTransaction, ...]


@dataclass(frozen=True, slots=True)
class RaiffeisenbankReportingFxResult:
    job_id: str
    reporting_currency: str
    transaction_ids: tuple[str, ...]
    exchange_rate_ids: tuple[str, ...]
    rates_created: int
    rates_replayed: int
    evidence_created: int
    evidence_replayed: int


@dataclass(frozen=True, slots=True)
class _PreparedEvidence:
    transaction: RaiffeisenbankReportingFxTransaction
    observation: ExchangeRateObservation
    reporting_amount: Decimal


@dataclass(frozen=True, slots=True)
class _PersistedEvidenceBundle:
    transaction_id: str
    source_amount: Decimal
    source_currency: str
    source_event_time: datetime
    reporting_amount: Decimal
    reporting_currency: str
    exchange_rate_id: str
    calculation_version: int
    background_job_id: str | None
    published_at: datetime | None
    evidence_created_at: datetime
    rate_id: str
    rate_from_currency: str
    rate_to_currency: str
    rate: Decimal
    rate_source: ExchangeRateSource
    rate_effective_at: datetime
    rate_created_at: datetime


class _Repository(Protocol):
    async def set_transaction_repeatable_read_only(self) -> None: ...

    async def set_transaction_serializable(self) -> None: ...

    async def acquire_locks(self, scopes: tuple[str, ...]) -> None: ...

    async def load_job(self, *, job_id: str, user_id: str) -> BackgroundJobModel | None: ...

    async def load_manifested_batches(
        self, *, job_id: str, user_id: str
    ) -> tuple[tuple[ImportJobBatchModel, ImportBatchModel], ...]: ...

    async def load_manifested_transactions(
        self, *, batch_ids: tuple[str, ...], for_update: bool
    ) -> tuple[TransactionModel, ...]: ...

    async def load_imported_transaction_links(
        self, *, batch_ids: tuple[str, ...]
    ) -> tuple[tuple[str, str, str | None], ...]: ...

    async def load_exchange_rate(
        self,
        *,
        from_currency: str,
        to_currency: str,
        effective_at: datetime,
        source: ExchangeRateSource,
    ) -> ExchangeRateModel | None: ...

    async def load_exchange_rate_by_id(self, rate_id: str) -> ExchangeRateModel | None: ...

    async def load_reporting_evidence(
        self, transaction_id: str
    ) -> TransactionReportingEvidenceModel | None: ...

    async def load_reporting_evidence_bundle(
        self, *, transaction_ids: tuple[str, ...]
    ) -> tuple[tuple[TransactionReportingEvidenceModel, ExchangeRateModel], ...]: ...

    def add_exchange_rate(self, row: ExchangeRateModel) -> None: ...

    def add_reporting_evidence(self, row: TransactionReportingEvidenceModel) -> None: ...

    async def flush(self) -> None: ...


def _fail() -> RaiffeisenbankReportingFxStateError:
    return RaiffeisenbankReportingFxStateError()


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _currency(value: object) -> str:
    result = _nonblank(value)
    if len(result) != 3 or result != result.upper() or not result.isascii() or not result.isalpha():
        raise _fail()
    return result


def _timestamp(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or value.microsecond % 1_000 != 0
    ):
        raise _fail()
    return value


def _money(value: object, *, nonzero: bool) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise _fail()
    try:
        canonical = value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
    except InvalidOperation as exc:
        raise _fail() from exc
    if canonical != value or (nonzero and canonical == 0):
        raise _fail()
    integer_digits = max(canonical.copy_abs().adjusted() + 1, 0) if canonical else 0
    if integer_digits > _MAX_MONEY_INTEGER_DIGITS:
        raise _fail()
    return canonical


def calculate_reporting_amount(source_amount: Decimal, rate: Decimal) -> Decimal:
    source = _money(source_amount, nonzero=True)
    if not isinstance(rate, Decimal) or not rate.is_finite() or rate <= 0:
        raise _fail()
    try:
        result = (source * rate).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
    except InvalidOperation as exc:
        raise _fail() from exc
    return _money(result, nonzero=True)


def _transaction(
    row: object,
    *,
    batch_accounts: dict[str, str],
    reporting_currency: str,
) -> RaiffeisenbankReportingFxTransaction:
    if not isinstance(row, TransactionModel):
        raise _fail()
    transaction_id = _nonblank(row.id)
    batch_id = _nonblank(row.import_batch_id)
    account_id = _nonblank(row.account_id)
    if batch_accounts.get(batch_id) != account_id:
        raise _fail()
    if (row.reporting_amount is None) != (row.reporting_currency is None):
        raise _fail()
    existing_reporting_amount = (
        None if row.reporting_amount is None else _money(row.reporting_amount, nonzero=True)
    )
    existing_reporting_currency = (
        None if row.reporting_currency is None else _currency(row.reporting_currency)
    )
    source_currency = _currency(row.currency)
    if existing_reporting_currency is not None and (
        source_currency == reporting_currency or existing_reporting_currency != reporting_currency
    ):
        raise _fail()
    return RaiffeisenbankReportingFxTransaction(
        transaction_id=transaction_id,
        batch_id=batch_id,
        account_id=account_id,
        source_amount=_money(row.amount, nonzero=True),
        source_currency=source_currency,
        source_event_time=_timestamp(row.date),
        existing_reporting_amount=existing_reporting_amount,
        existing_reporting_currency=existing_reporting_currency,
    )


async def _load_plan(
    repository: _Repository,
    *,
    job_id: str,
    user_id: str,
    reporting_currency: str,
    for_update: bool,
) -> RaiffeisenbankReportingFxPlan:
    job = await repository.load_job(job_id=job_id, user_id=user_id)
    if (
        not isinstance(job, BackgroundJobModel)
        or job.id != job_id
        or job.user_id != user_id
        or job.status is not BackgroundJobStatus.running
    ):
        raise _fail()
    manifested = await repository.load_manifested_batches(job_id=job_id, user_id=user_id)
    if not manifested:
        raise _fail()
    batch_accounts: dict[str, str] = {}
    for membership, batch in manifested:
        if (
            not isinstance(membership, ImportJobBatchModel)
            or not isinstance(batch, ImportBatchModel)
            or membership.job_id != job_id
            or membership.user_id != user_id
            or membership.batch_id != batch.id
            or membership.account_id != batch.account_id
            or batch.user_id != user_id
            or batch.source is not ImportSource.raiffeisenbank
            or batch.id in batch_accounts
        ):
            raise _fail()
        batch_accounts[batch.id] = batch.account_id
    batch_ids = tuple(sorted(batch_accounts))
    rows = await repository.load_manifested_transactions(
        batch_ids=batch_ids,
        for_update=for_update,
    )
    transactions = tuple(
        sorted(
            (
                _transaction(
                    row,
                    batch_accounts=batch_accounts,
                    reporting_currency=reporting_currency,
                )
                for row in rows
            ),
            key=lambda item: item.transaction_id,
        )
    )
    if len({item.transaction_id for item in transactions}) != len(transactions):
        raise _fail()
    links = await repository.load_imported_transaction_links(batch_ids=batch_ids)
    linked_transaction_ids: list[str] = []
    seen_row_ids: set[str] = set()
    for row_id, batch_id, transaction_id in links:
        canonical_row_id = _nonblank(row_id)
        canonical_batch_id = _nonblank(batch_id)
        if (
            canonical_row_id in seen_row_ids
            or canonical_batch_id not in batch_accounts
            or transaction_id is None
        ):
            raise _fail()
        seen_row_ids.add(canonical_row_id)
        linked_transaction_ids.append(_nonblank(transaction_id))
    if len(set(linked_transaction_ids)) != len(linked_transaction_ids) or tuple(
        sorted(linked_transaction_ids)
    ) != tuple(item.transaction_id for item in transactions):
        raise _fail()
    return RaiffeisenbankReportingFxPlan(
        job_id=job_id,
        user_id=user_id,
        reporting_currency=reporting_currency,
        transactions=transactions,
    )


def _rate_matches(
    row: object,
    observation: ExchangeRateObservation,
    expected_id: str,
) -> bool:
    return (
        isinstance(row, ExchangeRateModel)
        and row.id == expected_id
        and row.from_currency == observation.from_currency
        and row.to_currency == observation.to_currency
        and row.rate == observation.rate
        and row.source is observation.provider
        and row.date == observation.effective_at
        and isinstance(row.created_at, datetime)
    )


def _evidence_matches(
    row: object,
    prepared: _PreparedEvidence,
    *,
    job_id: str,
    reporting_currency: str,
    rate_id: str,
) -> bool:
    transaction = prepared.transaction
    return (
        isinstance(row, TransactionReportingEvidenceModel)
        and row.transaction_id == transaction.transaction_id
        and row.source_amount == transaction.source_amount
        and row.source_currency == transaction.source_currency
        and row.source_event_time == transaction.source_event_time
        and row.reporting_amount == prepared.reporting_amount
        and row.reporting_currency == reporting_currency
        and row.exchange_rate_id == rate_id
        and row.calculation_version == REPORTING_FX_CALCULATION_VERSION
        and row.background_job_id == job_id
        and (row.published_at is None or isinstance(row.published_at, datetime))
        and isinstance(row.created_at, datetime)
    )


def _persisted_bundle(
    evidence: object,
    rate: object,
) -> _PersistedEvidenceBundle:
    if not isinstance(evidence, TransactionReportingEvidenceModel) or not isinstance(
        rate, ExchangeRateModel
    ):
        raise _fail()
    return _PersistedEvidenceBundle(
        transaction_id=_nonblank(evidence.transaction_id),
        source_amount=_money(evidence.source_amount, nonzero=True),
        source_currency=_currency(evidence.source_currency),
        source_event_time=_timestamp(evidence.source_event_time),
        reporting_amount=_money(evidence.reporting_amount, nonzero=True),
        reporting_currency=_currency(evidence.reporting_currency),
        exchange_rate_id=_nonblank(evidence.exchange_rate_id),
        calculation_version=evidence.calculation_version,
        background_job_id=(
            None if evidence.background_job_id is None else _nonblank(evidence.background_job_id)
        ),
        published_at=(None if evidence.published_at is None else _timestamp(evidence.published_at)),
        evidence_created_at=_timestamp(evidence.created_at),
        rate_id=_nonblank(rate.id),
        rate_from_currency=_currency(rate.from_currency),
        rate_to_currency=_currency(rate.to_currency),
        rate=rate.rate,
        rate_source=rate.source,
        rate_effective_at=_timestamp(rate.date),
        rate_created_at=_timestamp(rate.created_at),
    )


def _sqlstate(error: BaseException) -> str | None:
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        candidate = pending.pop()
        if id(candidate) in seen:
            continue
        seen.add(id(candidate))
        for attribute in ("sqlstate", "pgcode"):
            value = getattr(candidate, attribute, None)
            if isinstance(value, str):
                return value
        for attribute in ("orig", "__cause__", "__context__"):
            nested = getattr(candidate, attribute, None)
            if isinstance(nested, BaseException):
                pending.append(nested)
    return None


class RaiffeisenbankReportingFxService:
    """Provider I/O is isolated between immutable planning and atomic writing."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        source_policy: MarketEvidenceSourcePolicy,
        fx_registry: ExchangeRateProviderRegistry,
        policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
        repository: _Repository | None = None,
    ) -> None:
        self.session = session
        self.source_policy = validate_market_evidence_source_policy(source_policy)
        self.fx_registry = fx_registry
        if self.fx_registry.sources != frozenset({self.source_policy.fx_source}):
            raise _fail()
        self.policy = validate_market_evidence_policy(policy)
        self.repository = repository or RaiffeisenbankReportingFxRepository(session)

    async def acquire(
        self,
        command: AcquireRaiffeisenbankReportingFxCommand,
    ) -> RaiffeisenbankReportingFxResult:
        if not isinstance(command, AcquireRaiffeisenbankReportingFxCommand):
            raise _fail()
        job_id = _nonblank(command.job_id)
        user_id = _nonblank(command.user_id)
        reporting_currency = _currency(command.reporting_currency)
        if not isinstance(command.canonical_transaction_ids, tuple):
            raise _fail()
        canonical_transaction_ids = tuple(
            _nonblank(item) for item in command.canonical_transaction_ids
        )
        if canonical_transaction_ids != tuple(sorted(set(canonical_transaction_ids))):
            raise _fail()
        created_at = _timestamp(command.created_at)
        if self.session.in_transaction():
            raise _fail()
        async with self.session.begin():
            await self.repository.set_transaction_repeatable_read_only()
            plan = await _load_plan(
                self.repository,
                job_id=job_id,
                user_id=user_id,
                reporting_currency=reporting_currency,
                for_update=False,
            )
            if canonical_transaction_ids != tuple(
                item.transaction_id for item in plan.transactions
            ):
                raise _fail()
            persisted_bundles = tuple(
                _persisted_bundle(evidence, rate)
                for evidence, rate in (
                    await self.repository.load_reporting_evidence_bundle(
                        transaction_ids=canonical_transaction_ids,
                    )
                )
            )
        if self.session.in_transaction():
            raise _fail()

        foreign_transactions = tuple(
            item for item in plan.transactions if item.source_currency != reporting_currency
        )
        transactions_by_id = {item.transaction_id: item for item in plan.transactions}
        persisted_prepared: dict[str, _PreparedEvidence] = {}
        for bundle in persisted_bundles:
            if bundle.transaction_id in persisted_prepared:
                raise _fail()
            transaction = transactions_by_id.get(bundle.transaction_id)
            if transaction is None or transaction.source_currency == reporting_currency:
                raise _fail()
            observation = ExchangeRateObservation(
                from_currency=bundle.rate_from_currency,
                to_currency=bundle.rate_to_currency,
                provider=bundle.rate_source,
                rate=bundle.rate,
                effective_at=bundle.rate_effective_at,
            )
            requirement = ExchangeRateRequirement(
                from_currency=transaction.source_currency,
                to_currency=reporting_currency,
                through=transaction.source_event_time,
                provider=self.source_policy.fx_source,
            )
            try:
                validated_observation = validate_exchange_rate_observation(
                    observation,
                    requirement=requirement,
                    policy=self.policy,
                )
            except ExchangeRateObservationValidationError as exc:
                raise _fail() from exc
            prepared_item = _PreparedEvidence(
                transaction=transaction,
                observation=validated_observation,
                reporting_amount=calculate_reporting_amount(
                    transaction.source_amount,
                    validated_observation.rate,
                ),
            )
            expected_rate_id = exchange_rate_id(validated_observation)
            if (
                bundle.rate_id != expected_rate_id
                or bundle.exchange_rate_id != expected_rate_id
                or bundle.source_amount != transaction.source_amount
                or bundle.source_currency != transaction.source_currency
                or bundle.source_event_time != transaction.source_event_time
                or bundle.reporting_amount != prepared_item.reporting_amount
                or bundle.reporting_currency != reporting_currency
                or bundle.calculation_version != REPORTING_FX_CALCULATION_VERSION
                or bundle.background_job_id != job_id
                or transaction.existing_reporting_amount != prepared_item.reporting_amount
                or transaction.existing_reporting_currency != reporting_currency
            ):
                raise RaiffeisenbankReportingFxConflictError()
            persisted_prepared[transaction.transaction_id] = prepared_item
        for transaction in plan.transactions:
            has_persisted = transaction.transaction_id in persisted_prepared
            if transaction.source_currency == reporting_currency:
                if (
                    has_persisted
                    or transaction.existing_reporting_amount is not None
                    or transaction.existing_reporting_currency is not None
                ):
                    raise RaiffeisenbankReportingFxConflictError()
            elif not has_persisted and (
                transaction.existing_reporting_amount is not None
                or transaction.existing_reporting_currency is not None
            ):
                raise RaiffeisenbankReportingFxConflictError()
        missing_transactions = tuple(
            item for item in foreign_transactions if item.transaction_id not in persisted_prepared
        )
        requirements = tuple(
            ExchangeRateRequirement(
                from_currency=item.source_currency,
                to_currency=reporting_currency,
                through=item.source_event_time,
                provider=self.source_policy.fx_source,
            )
            for item in missing_transactions
        )
        provider = self.fx_registry.get(self.source_policy.fx_source)
        try:
            if requirements and isinstance(provider, BatchExchangeRateProvider):
                observations = await provider.fetch_many(requirements)
            else:
                observations = tuple(
                    [await provider.fetch(requirement) for requirement in requirements]
                )
            if not isinstance(observations, tuple) or len(observations) != len(requirements):
                raise _fail()
            validated = tuple(
                validate_exchange_rate_observation(
                    observation,
                    requirement=requirement,
                    policy=self.policy,
                )
                for observation, requirement in zip(observations, requirements, strict=True)
            )
        except (
            ExchangeRateObservationValidationError,
            MarketEvidenceStateError,
            RaiffeisenbankReportingFxStateError,
        ) as exc:
            raise _fail() from exc
        except Exception as exc:
            raise _fail() from exc
        acquired_prepared = {
            transaction.transaction_id: _PreparedEvidence(
                transaction=transaction,
                observation=observation,
                reporting_amount=calculate_reporting_amount(
                    transaction.source_amount,
                    observation.rate,
                ),
            )
            for transaction, observation in zip(missing_transactions, validated, strict=True)
        }
        prepared_by_id = persisted_prepared | acquired_prepared
        prepared = tuple(prepared_by_id[item.transaction_id] for item in foreign_transactions)
        return await self._write(
            plan=plan,
            prepared=prepared,
            created_at=created_at,
        )

    async def _write(
        self,
        *,
        plan: RaiffeisenbankReportingFxPlan,
        prepared: tuple[_PreparedEvidence, ...],
        created_at: datetime,
    ) -> RaiffeisenbankReportingFxResult:
        for attempt in range(_MAX_TRANSACTION_ATTEMPTS):
            try:
                async with self.session.begin():
                    return await self._write_attempt(
                        plan=plan,
                        prepared=prepared,
                        created_at=created_at,
                    )
            except (
                RaiffeisenbankReportingFxConflictError,
                RaiffeisenbankReportingFxStateError,
            ):
                raise
            except SQLAlchemyError as exc:
                if (
                    _sqlstate(exc) in _RETRYABLE_SQLSTATES
                    and attempt + 1 < _MAX_TRANSACTION_ATTEMPTS
                ):
                    continue
                raise _fail() from exc
        raise _fail()

    async def _write_attempt(
        self,
        *,
        plan: RaiffeisenbankReportingFxPlan,
        prepared: tuple[_PreparedEvidence, ...],
        created_at: datetime,
    ) -> RaiffeisenbankReportingFxResult:
        await self.repository.set_transaction_serializable()
        rate_observations: dict[
            tuple[str, str, datetime, ExchangeRateSource], ExchangeRateObservation
        ] = {}
        for item in prepared:
            observation = item.observation
            identity = (
                observation.from_currency,
                observation.to_currency,
                observation.effective_at,
                observation.provider,
            )
            existing = rate_observations.get(identity)
            if existing is not None and existing != observation:
                raise _fail()
            rate_observations[identity] = observation
        ordered_rates = tuple(
            sorted(
                rate_observations.values(),
                key=lambda item: (
                    item.from_currency,
                    item.to_currency,
                    item.effective_at,
                    item.provider.value,
                ),
            )
        )
        scopes = tuple(
            sorted(
                (
                    reporting_fx_job_lock_scope(plan.job_id),
                    *(
                        reporting_fx_rate_lock_scope(
                            from_currency=item.from_currency,
                            to_currency=item.to_currency,
                            effective_at=item.effective_at,
                            source=item.provider,
                        )
                        for item in ordered_rates
                    ),
                )
            )
        )
        await self.repository.acquire_locks(scopes)
        current = await _load_plan(
            self.repository,
            job_id=plan.job_id,
            user_id=plan.user_id,
            reporting_currency=plan.reporting_currency,
            for_update=True,
        )
        if current != plan:
            raise RaiffeisenbankReportingFxConflictError()

        rates_created = 0
        rates_replayed = 0
        rate_ids: dict[tuple[str, str, datetime, ExchangeRateSource], str] = {}
        for observation in ordered_rates:
            identity = (
                observation.from_currency,
                observation.to_currency,
                observation.effective_at,
                observation.provider,
            )
            expected_id = exchange_rate_id(observation)
            rate_ids[identity] = expected_id
            existing_rate = await self.repository.load_exchange_rate(
                from_currency=observation.from_currency,
                to_currency=observation.to_currency,
                effective_at=observation.effective_at,
                source=observation.provider,
            )
            if existing_rate is not None:
                if not _rate_matches(existing_rate, observation, expected_id):
                    raise RaiffeisenbankReportingFxConflictError()
                rates_replayed += 1
                continue
            if await self.repository.load_exchange_rate_by_id(expected_id) is not None:
                raise RaiffeisenbankReportingFxConflictError()
            self.repository.add_exchange_rate(
                ExchangeRateModel(
                    id=expected_id,
                    from_currency=observation.from_currency,
                    to_currency=observation.to_currency,
                    rate=observation.rate,
                    source=observation.provider,
                    date=observation.effective_at,
                    created_at=created_at,
                )
            )
            rates_created += 1

        current_rows = (
            await self.repository.load_manifested_transactions(
                batch_ids=tuple(sorted({item.batch_id for item in plan.transactions})),
                for_update=True,
            )
            if plan.transactions
            else ()
        )
        rows_by_id = {row.id: row for row in current_rows}
        evidence_created = 0
        evidence_replayed = 0
        for item in prepared:
            transaction = item.transaction
            row = rows_by_id.get(transaction.transaction_id)
            if row is None:
                raise RaiffeisenbankReportingFxConflictError()
            observation = item.observation
            rate_id = rate_ids[
                (
                    observation.from_currency,
                    observation.to_currency,
                    observation.effective_at,
                    observation.provider,
                )
            ]
            existing_evidence = await self.repository.load_reporting_evidence(
                transaction.transaction_id
            )
            if existing_evidence is not None:
                if not _evidence_matches(
                    existing_evidence,
                    item,
                    job_id=plan.job_id,
                    reporting_currency=plan.reporting_currency,
                    rate_id=rate_id,
                ) or (
                    row.reporting_amount != item.reporting_amount
                    or row.reporting_currency != plan.reporting_currency
                ):
                    raise RaiffeisenbankReportingFxConflictError()
                evidence_replayed += 1
                continue
            if row.reporting_amount is not None or row.reporting_currency is not None:
                raise RaiffeisenbankReportingFxConflictError()
            self.repository.add_reporting_evidence(
                TransactionReportingEvidenceModel(
                    transaction_id=transaction.transaction_id,
                    source_amount=transaction.source_amount,
                    source_currency=transaction.source_currency,
                    source_event_time=transaction.source_event_time,
                    reporting_amount=item.reporting_amount,
                    reporting_currency=plan.reporting_currency,
                    exchange_rate_id=rate_id,
                    calculation_version=REPORTING_FX_CALCULATION_VERSION,
                    background_job_id=plan.job_id,
                    published_at=None,
                    created_at=created_at,
                )
            )
            row.reporting_amount = item.reporting_amount
            row.reporting_currency = plan.reporting_currency
            evidence_created += 1

        prepared_ids = {item.transaction.transaction_id for item in prepared}
        for transaction in plan.transactions:
            if transaction.transaction_id in prepared_ids:
                continue
            row = rows_by_id.get(transaction.transaction_id)
            if row is None:
                raise RaiffeisenbankReportingFxConflictError()
            if row.reporting_amount is not None or row.reporting_currency is not None:
                raise RaiffeisenbankReportingFxConflictError()
            if (
                await self.repository.load_reporting_evidence(transaction.transaction_id)
                is not None
            ):
                raise RaiffeisenbankReportingFxConflictError()

        await self.repository.flush()
        return RaiffeisenbankReportingFxResult(
            job_id=plan.job_id,
            reporting_currency=plan.reporting_currency,
            transaction_ids=tuple(item.transaction.transaction_id for item in prepared),
            exchange_rate_ids=tuple(sorted(rate_ids.values())),
            rates_created=rates_created,
            rates_replayed=rates_replayed,
            evidence_created=evidence_created,
            evidence_replayed=evidence_replayed,
        )


__all__ = [
    "REPORTING_FX_CALCULATION_VERSION",
    "AcquireRaiffeisenbankReportingFxCommand",
    "RaiffeisenbankReportingFxConflictError",
    "RaiffeisenbankReportingFxResult",
    "RaiffeisenbankReportingFxService",
    "RaiffeisenbankReportingFxStateError",
    "RaiffeisenbankReportingFxTransaction",
    "calculate_reporting_amount",
]
