"""Fail-closed production composition for every durable history job kind."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.db.models.enums import ExchangeRateSource, PriceSource
from app.modules.market_data.history.factory import (
    create_canonical_historical_providers,
    create_local_free_historical_providers,
)
from app.modules.market_data.history.providers import (
    HistoricalExchangeRateProvider,
    HistoricalPriceProvider,
)
from app.modules.market_data.policy import MarketEvidencePolicy
from app.modules.market_data.source_policy import (
    MarketEvidenceSourcePolicy,
    market_evidence_source_policy_from_settings,
)
from app.modules.portfolio_history.builder.executor import RebuildPortfolioHistoryJobExecutor
from app.modules.portfolio_history.builder.market import HistoricalMarketAcquirer
from app.modules.portfolio_history.jobs.dispatch import PortfolioHistoryJobDispatchExecutor
from app.modules.portfolio_history.jobs.worker import (
    PortfolioHistoryJobExecutor,
    PortfolioHistoryJobWorker,
    PortfolioHistoryWorkerRunner,
)
from app.modules.snapshot_refresh.series_executor import SnapshotSeriesExecutor
from app.modules.snapshot_refresh.series_persistence import (
    PostgresAtomicSnapshotSeriesPublisher,
    PostgresSnapshotSeriesAccountStager,
    PostgresSnapshotSeriesUserProjectionStager,
)

PORTFOLIO_HISTORY_CALCULATION_VERSION = 1
PORTFOLIO_HISTORY_MARKET_EVIDENCE_POLICY = MarketEvidencePolicy(
    maximum_price_age=timedelta(days=7),
    maximum_fx_age=timedelta(days=7),
)


@dataclass(frozen=True, slots=True)
class HistoricalProviderBundle:
    price_providers: Mapping[PriceSource, HistoricalPriceProvider]
    fx_providers: Mapping[ExchangeRateSource, HistoricalExchangeRateProvider]


@dataclass(frozen=True, slots=True)
class PortfolioHistoryWorkerSettings:
    worker_id: str
    lease_duration: timedelta
    heartbeat_interval: timedelta
    poll_interval: float


def _validated_provider_bundle(
    bundle: HistoricalProviderBundle,
    *,
    source_policy: MarketEvidenceSourcePolicy,
) -> HistoricalProviderBundle:
    if (
        not isinstance(bundle, HistoricalProviderBundle)
        or set(bundle.price_providers) != set(source_policy.price_sources)
        or set(bundle.fx_providers) != {source_policy.fx_source}
        or any(provider is None for provider in bundle.price_providers.values())
        or any(provider is None for provider in bundle.fx_providers.values())
        or any(
            provider.capability.source is not source
            for source, provider in bundle.price_providers.items()
        )
        or any(
            provider.capability.source is not source
            for source, provider in bundle.fx_providers.items()
        )
    ):
        raise ValueError("Portfolio history historical providers are incomplete.")
    return bundle


def create_historical_provider_bundle(
    settings: Settings,
    *,
    source_policy: MarketEvidenceSourcePolicy,
) -> HistoricalProviderBundle:
    if source_policy.mode == "canonical":
        canonical_listed, canonical_crypto, canonical_fx = create_canonical_historical_providers(
            settings
        )
        bundle = HistoricalProviderBundle(
            price_providers={
                PriceSource.twelve_data: canonical_listed,
                PriceSource.coingecko: canonical_crypto,
            },
            fx_providers={ExchangeRateSource.twelve_data: canonical_fx},
        )
    elif source_policy.mode == "local_free":
        local_listed, local_crypto, local_fx = create_local_free_historical_providers(settings)
        bundle = HistoricalProviderBundle(
            price_providers={
                PriceSource.yahoo_finance: local_listed,
                PriceSource.coingecko: local_crypto,
            },
            fx_providers={ExchangeRateSource.yahoo_finance: local_fx},
        )
    else:  # pragma: no cover - validated source policy owns this branch.
        raise ValueError("Portfolio history source policy is not configured.")
    return _validated_provider_bundle(bundle, source_policy=source_policy)


def create_portfolio_history_dispatch_executor(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    providers: HistoricalProviderBundle | None = None,
) -> PortfolioHistoryJobDispatchExecutor:
    if not isinstance(settings, Settings):
        raise ValueError("Portfolio history settings are invalid.")
    source_policy = market_evidence_source_policy_from_settings(settings)
    bundle = _validated_provider_bundle(
        providers or create_historical_provider_bundle(settings, source_policy=source_policy),
        source_policy=source_policy,
    )
    market_acquirer = HistoricalMarketAcquirer(
        price_providers=bundle.price_providers,
        fx_providers=bundle.fx_providers,
        source_policy=source_policy,
        evidence_policy=PORTFOLIO_HISTORY_MARKET_EVIDENCE_POLICY,
    )
    snapshot_series_executor = SnapshotSeriesExecutor(
        account_stager=PostgresSnapshotSeriesAccountStager(session_factory),
        user_projection_stager=PostgresSnapshotSeriesUserProjectionStager(session_factory),
        publisher=PostgresAtomicSnapshotSeriesPublisher(session_factory),
    )
    return PortfolioHistoryJobDispatchExecutor(
        rebuild=RebuildPortfolioHistoryJobExecutor(
            session_factory,
            source_policy=source_policy,
            market_acquirer=market_acquirer,
            calculation_version=PORTFOLIO_HISTORY_CALCULATION_VERSION,
            snapshot_series_executor=snapshot_series_executor,
        ),
    )


def create_portfolio_history_worker_runner(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: PortfolioHistoryWorkerSettings,
    executor: PortfolioHistoryJobExecutor,
) -> PortfolioHistoryWorkerRunner:
    worker = PortfolioHistoryJobWorker(
        session_factory,
        executor,
        worker_id=settings.worker_id,
        lease_duration=settings.lease_duration,
        heartbeat_interval=settings.heartbeat_interval,
    )
    return PortfolioHistoryWorkerRunner(worker, poll_interval=settings.poll_interval)


__all__ = [
    "PORTFOLIO_HISTORY_CALCULATION_VERSION",
    "HistoricalProviderBundle",
    "PortfolioHistoryWorkerSettings",
    "create_historical_provider_bundle",
    "create_portfolio_history_dispatch_executor",
    "create_portfolio_history_worker_runner",
]
