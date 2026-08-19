from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, cast

import pytest

from app.db.models.background_jobs import BackgroundJobModel, ImportJobBatchModel
from app.db.models.enums import (
    BackgroundJobKind,
    BackgroundJobStatus,
    ExchangeRateSource,
    ImportSource,
    TransactionType,
)
from app.db.models.imports import ImportBatchModel
from app.db.models.prices import ExchangeRateModel
from app.db.models.transactions import TransactionModel, TransactionReportingEvidenceModel
from app.modules.fx.models import ExchangeRateObservation
from app.modules.imports.raiffeisenbank_reporting_fx import (
    AcquireRaiffeisenbankReportingFxCommand,
    RaiffeisenbankReportingFxConflictError,
    RaiffeisenbankReportingFxService,
    RaiffeisenbankReportingFxStateError,
    calculate_reporting_amount,
)
from app.modules.market_data.models import ExchangeRateRequirement
from app.modules.market_data.providers import ExchangeRateProviderRegistry
from app.modules.market_data.source_policy import (
    CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
    LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
)
from app.modules.market_data.writer import exchange_rate_id

EVENT_AT = datetime(2026, 1, 15, 14, 30, 0, 123000)
RATE_AT = datetime(2026, 1, 15)
CREATED_AT = datetime(2026, 8, 19, 22)


class _TransactionContext:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> None:
        self.session.active = True
        self.session.begin_count += 1

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.session.active = False
        if exc_type is None:
            self.session.commit_count += 1
        else:
            self.session.rollback_count += 1


class _Session:
    def __init__(self) -> None:
        self.active = False
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    def in_transaction(self) -> bool:
        return self.active

    def begin(self) -> _TransactionContext:
        return _TransactionContext(self)


class _Provider:
    def __init__(
        self,
        session: _Session,
        *,
        source: ExchangeRateSource = ExchangeRateSource.yahoo_finance,
    ) -> None:
        self.source = source
        self.session = session
        self.requirements: list[tuple[ExchangeRateRequirement, ...]] = []
        self.mutate: Any = None
        self.wrong_count = False

    async def fetch(self, requirement: ExchangeRateRequirement) -> ExchangeRateObservation:
        return (await self.fetch_many((requirement,)))[0]

    async def fetch_many(
        self,
        requirements: tuple[ExchangeRateRequirement, ...],
    ) -> tuple[ExchangeRateObservation, ...]:
        assert not self.session.in_transaction()
        self.requirements.append(requirements)
        if self.mutate is not None:
            self.mutate()
        observations = tuple(
            ExchangeRateObservation(
                item.from_currency,
                item.to_currency,
                self.source,
                Decimal("25.12345678"),
                RATE_AT,
            )
            for item in requirements
        )
        return observations[:-1] if self.wrong_count else observations


class _Repository:
    def __init__(self, *, amount: str = "-10.000000", currency: str = "EUR") -> None:
        self.job = BackgroundJobModel(
            id="job-1",
            user_id="user-1",
            account_id="account-1",
            kind=BackgroundJobKind.import_workflow,
            status=BackgroundJobStatus.running,
        )
        self.membership = ImportJobBatchModel(
            job_id="job-1",
            batch_id="batch-1",
            user_id="user-1",
            account_id="account-1",
        )
        self.batch = ImportBatchModel(
            id="batch-1",
            user_id="user-1",
            account_id="account-1",
            source=ImportSource.raiffeisenbank,
        )
        self.transaction = TransactionModel(
            id="transaction-1",
            date=EVENT_AT,
            amount=Decimal(amount),
            currency=currency,
            reporting_amount=None,
            reporting_currency=None,
            type=TransactionType.expense,
            account_id="account-1",
            import_batch_id="batch-1",
        )
        self.rates: dict[str, ExchangeRateModel] = {}
        self.evidence: dict[str, TransactionReportingEvidenceModel] = {}
        self.calls: list[object] = []

    async def set_transaction_repeatable_read_only(self) -> None:
        self.calls.append("read-only")

    async def set_transaction_serializable(self) -> None:
        self.calls.append("serializable")

    async def acquire_locks(self, scopes: tuple[str, ...]) -> None:
        self.calls.append(("locks", scopes))

    async def load_job(self, **values: str) -> BackgroundJobModel | None:
        if values == {"job_id": "job-1", "user_id": "user-1"}:
            return self.job
        return None

    async def load_manifested_batches(
        self, **values: str
    ) -> tuple[tuple[ImportJobBatchModel, ImportBatchModel], ...]:
        if values == {"job_id": "job-1", "user_id": "user-1"}:
            return ((self.membership, self.batch),)
        return ()

    async def load_manifested_transactions(
        self, *, batch_ids: tuple[str, ...], for_update: bool
    ) -> tuple[TransactionModel, ...]:
        self.calls.append(("transactions", batch_ids, for_update))
        return (self.transaction,)

    async def load_imported_transaction_links(
        self, *, batch_ids: tuple[str, ...]
    ) -> tuple[tuple[str, str, str | None], ...]:
        assert batch_ids == ("batch-1",)
        return (("row-1", "batch-1", "transaction-1"),)

    async def load_exchange_rate(self, **values: object) -> ExchangeRateModel | None:
        for row in self.rates.values():
            if (
                row.from_currency == values["from_currency"]
                and row.to_currency == values["to_currency"]
                and row.date == values["effective_at"]
                and row.source is values["source"]
            ):
                return row
        return None

    async def load_exchange_rate_by_id(self, rate_id: str) -> ExchangeRateModel | None:
        return self.rates.get(rate_id)

    async def load_reporting_evidence(
        self, transaction_id: str
    ) -> TransactionReportingEvidenceModel | None:
        return self.evidence.get(transaction_id)

    async def load_reporting_evidence_bundle(
        self, *, transaction_ids: tuple[str, ...]
    ) -> tuple[tuple[TransactionReportingEvidenceModel, ExchangeRateModel], ...]:
        bundles: list[tuple[TransactionReportingEvidenceModel, ExchangeRateModel]] = []
        for transaction_id in transaction_ids:
            evidence = self.evidence.get(transaction_id)
            if evidence is not None:
                rate = self.rates.get(evidence.exchange_rate_id)
                if rate is not None:
                    bundles.append((evidence, rate))
        return tuple(bundles)

    def add_exchange_rate(self, row: ExchangeRateModel) -> None:
        self.rates[row.id] = row

    def add_reporting_evidence(self, row: TransactionReportingEvidenceModel) -> None:
        self.evidence[row.transaction_id] = row

    async def flush(self) -> None:
        self.calls.append("flush")


def _service(
    *,
    amount: str = "-10.000000",
    currency: str = "EUR",
) -> tuple[RaiffeisenbankReportingFxService, _Session, _Repository, _Provider]:
    session = _Session()
    repository = _Repository(amount=amount, currency=currency)
    provider = _Provider(session)
    service = RaiffeisenbankReportingFxService(
        cast(Any, session),
        source_policy=LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
        fx_registry=ExchangeRateProviderRegistry((provider,)),
        repository=repository,
    )
    return service, session, repository, provider


def _command() -> AcquireRaiffeisenbankReportingFxCommand:
    return AcquireRaiffeisenbankReportingFxCommand(
        job_id="job-1",
        user_id="user-1",
        reporting_currency="CZK",
        canonical_transaction_ids=("transaction-1",),
        created_at=CREATED_AT,
    )


def test_money_uses_exact_half_even_and_rejects_unrepresentable_values() -> None:
    assert calculate_reporting_amount(Decimal("1.000000"), Decimal("1.2345565")) == Decimal(
        "1.234556"
    )
    assert calculate_reporting_amount(Decimal("1.000000"), Decimal("1.2345575")) == Decimal(
        "1.234558"
    )
    with pytest.raises(RaiffeisenbankReportingFxStateError):
        calculate_reporting_amount(Decimal("1000000000000.000000"), Decimal("1"))


def test_service_accepts_exactly_one_policy_owned_direct_provider() -> None:
    session = _Session()
    yahoo = _Provider(session)
    twelve = _Provider(session, source=ExchangeRateSource.twelve_data)
    with pytest.raises(RaiffeisenbankReportingFxStateError):
        RaiffeisenbankReportingFxService(
            cast(Any, session),
            source_policy=LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
            fx_registry=ExchangeRateProviderRegistry((yahoo, twelve)),
            repository=_Repository(),
        )
    RaiffeisenbankReportingFxService(
        cast(Any, session),
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        fx_registry=ExchangeRateProviderRegistry((twelve,)),
        repository=_Repository(),
    )


@pytest.mark.asyncio
async def test_direct_event_date_evidence_is_atomic_and_exactly_replayable() -> None:
    service, session, repository, provider = _service(amount="-10.005000")

    created = await service.acquire(_command())
    replayed = await service.acquire(_command())

    assert provider.requirements == [
        (
            ExchangeRateRequirement(
                "EUR",
                "CZK",
                EVENT_AT,
                ExchangeRateSource.yahoo_finance,
            ),
        )
    ]
    observation = ExchangeRateObservation(
        "EUR",
        "CZK",
        ExchangeRateSource.yahoo_finance,
        Decimal("25.12345678"),
        RATE_AT,
    )
    rate_id = exchange_rate_id(observation)
    expected_amount = Decimal("-251.360185")
    assert created.exchange_rate_ids == replayed.exchange_rate_ids == (rate_id,)
    assert (created.rates_created, created.rates_replayed) == (1, 0)
    assert (created.evidence_created, created.evidence_replayed) == (1, 0)
    assert (replayed.rates_created, replayed.rates_replayed) == (0, 1)
    assert (replayed.evidence_created, replayed.evidence_replayed) == (0, 1)
    evidence = repository.evidence["transaction-1"]
    assert evidence.source_event_time == EVENT_AT
    assert evidence.exchange_rate_id == rate_id
    assert evidence.reporting_amount == expected_amount
    assert evidence.background_job_id == "job-1"
    assert evidence.published_at is None
    assert repository.transaction.reporting_amount == expected_amount
    assert repository.transaction.reporting_currency == "CZK"
    assert session.begin_count == session.commit_count == 4
    assert session.rollback_count == 0


@pytest.mark.asyncio
async def test_same_currency_never_requests_or_persists_fx() -> None:
    service, _, repository, provider = _service(currency="CZK")
    result = await service.acquire(_command())
    assert provider.requirements == []
    assert result.transaction_ids == result.exchange_rate_ids == ()
    assert result.evidence_created == result.rates_created == 0
    assert repository.rates == repository.evidence == {}
    assert repository.transaction.reporting_amount is None
    assert repository.transaction.reporting_currency is None


@pytest.mark.asyncio
async def test_completed_job_cannot_acquire_or_mutate_reporting_evidence() -> None:
    service, _, repository, provider = _service()
    repository.job.status = BackgroundJobStatus.completed

    with pytest.raises(RaiffeisenbankReportingFxStateError):
        await service.acquire(_command())

    assert provider.requirements == []
    assert repository.rates == repository.evidence == {}


@pytest.mark.asyncio
async def test_scope_change_between_provider_and_writer_fails_closed() -> None:
    service, session, repository, provider = _service()
    provider.mutate = lambda: setattr(repository.transaction, "amount", Decimal("-11.000000"))
    with pytest.raises(RaiffeisenbankReportingFxConflictError):
        await service.acquire(_command())
    assert repository.rates == repository.evidence == {}
    assert session.rollback_count == 1


@pytest.mark.asyncio
async def test_provider_missing_observation_and_foreign_evidence_fail_closed() -> None:
    service, _, repository, provider = _service()
    provider.wrong_count = True
    with pytest.raises(RaiffeisenbankReportingFxStateError):
        await service.acquire(_command())
    assert repository.rates == repository.evidence == {}

    provider.wrong_count = False
    observation = ExchangeRateObservation(
        "EUR",
        "CZK",
        ExchangeRateSource.yahoo_finance,
        Decimal("25.12345678"),
        RATE_AT,
    )
    rate_id = exchange_rate_id(observation)
    repository.rates[rate_id] = ExchangeRateModel(
        id=rate_id,
        from_currency="EUR",
        to_currency="CZK",
        rate=observation.rate,
        source=observation.provider,
        date=RATE_AT,
        created_at=CREATED_AT,
    )
    repository.evidence["transaction-1"] = TransactionReportingEvidenceModel(
        transaction_id="transaction-1",
        source_amount=Decimal("-10.000000"),
        source_currency="EUR",
        source_event_time=EVENT_AT,
        reporting_amount=Decimal("-251.234568"),
        reporting_currency="CZK",
        exchange_rate_id=rate_id,
        calculation_version=1,
        background_job_id="foreign-job",
        published_at=None,
        created_at=CREATED_AT,
    )
    repository.transaction.reporting_amount = Decimal("-251.234568")
    repository.transaction.reporting_currency = "CZK"
    with pytest.raises(RaiffeisenbankReportingFxConflictError):
        await service.acquire(_command())


@pytest.mark.asyncio
async def test_non_rb_or_missing_manifest_is_rejected_before_provider_io() -> None:
    service, _, repository, provider = _service()
    repository.batch.source = ImportSource.manual
    with pytest.raises(RaiffeisenbankReportingFxStateError):
        await service.acquire(_command())
    assert provider.requirements == []


@pytest.mark.asyncio
async def test_explicit_canonical_transaction_scope_must_equal_manifest() -> None:
    service, _, _, provider = _service()
    command = _command()
    with pytest.raises(RaiffeisenbankReportingFxStateError):
        await service.acquire(
            AcquireRaiffeisenbankReportingFxCommand(
                job_id=command.job_id,
                user_id=command.user_id,
                reporting_currency=command.reporting_currency,
                canonical_transaction_ids=(),
                created_at=command.created_at,
            )
        )
    assert provider.requirements == []
