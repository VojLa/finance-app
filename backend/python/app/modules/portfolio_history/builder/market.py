"""Grouped historical evidence acquisition for frozen replay states."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.db.models.enums import ExchangeRateSource, PriceSource
from app.modules.fx.models import ExchangeRateObservation
from app.modules.market_data.history.models import (
    HistoricalExchangeRateRangeRequirement,
    HistoricalPriceRangeRequirement,
    HistoricalTimeSeriesInterval,
)
from app.modules.market_data.history.providers import (
    HistoricalExchangeRateProvider,
    HistoricalPriceProvider,
)
from app.modules.market_data.history.selection import (
    select_historical_exchange_rates,
    select_historical_prices,
)
from app.modules.market_data.policy import MarketEvidencePolicy
from app.modules.market_data.source_policy import MarketEvidenceSourcePolicy
from app.modules.market_data.writer import exchange_rate_id, price_snapshot_id
from app.modules.portfolio_history.builder.planning import HistoryGenerationBuildError
from app.modules.portfolio_history_rebuild.models import AccountReplayState
from app.modules.portfolio_history_rebuild.repository import (
    FrozenAccountReplayInput,
    FrozenListingIdentity,
    FrozenPortfolioReplayInput,
)
from app.modules.prices.models import PriceObservation
from app.modules.snapshot_refresh.metric_evidence import build_historical_metric_evidence
from app.modules.snapshots.financial_metrics import AccountSnapshotEvidenceStateError

_MAX_REQUEST_TIMESTAMPS = 4_096
_MAX_PARALLEL_CALLS = 8


@dataclass(frozen=True, slots=True)
class SelectedHistoricalPrice:
    account_id: str
    through: datetime
    listing: FrozenListingIdentity
    price_id: str
    observation: PriceObservation


@dataclass(frozen=True, slots=True)
class SelectedHistoricalRate:
    account_id: str
    through: datetime
    rate_id: str
    observation: ExchangeRateObservation
    consumed: bool


@dataclass(frozen=True, slots=True)
class SelectedHistoricalSnapshotRate:
    """One valuation-FX selection for the snapshot-series native/base outputs.

    These rates intentionally remain separate from ``SelectedHistoricalRate``:
    the retained-history generation only values in the user's base currency and
    its strict projection rejects unused native-output rates.
    """

    account_id: str
    through: datetime
    output_currency: str
    rate_id: str
    observation: ExchangeRateObservation


@dataclass(frozen=True, slots=True)
class SelectedHistoricalMetricRate:
    """One event-date FX selection for a frozen financial metric."""

    account_id: str
    evidence_id: str
    event_at: datetime
    output_currency: str
    rate_id: str
    observation: ExchangeRateObservation


@dataclass(frozen=True, slots=True)
class HistoricalMarketSelection:
    prices: tuple[SelectedHistoricalPrice, ...]
    rates: tuple[SelectedHistoricalRate, ...]
    price_observations: tuple[PriceObservation, ...]
    rate_observations: tuple[ExchangeRateObservation, ...]
    provider_call_count: int
    snapshot_rates: tuple[SelectedHistoricalSnapshotRate, ...] = ()
    metric_rates: tuple[SelectedHistoricalMetricRate, ...] = ()


class HistoricalMarketLookbackUnavailableError(HistoryGenerationBuildError):
    """Required source evidence is beyond its declared provider retention."""


def _maximum_age_for_interval(
    provider: object, interval: HistoricalTimeSeriesInterval
) -> timedelta | None:
    capability = getattr(provider, "capability", None)
    ranges = getattr(capability, "ranges", ())
    matched = tuple(item for item in ranges if item.requested_interval is interval)
    if not matched:
        return None
    ages = tuple(item.maximum_age for item in matched)
    return None if any(age is None for age in ages) else max(ages)


def _require_available(
    provider: object, interval: HistoricalTimeSeriesInterval, *, at: datetime, as_of: datetime
) -> None:
    maximum_age = _maximum_age_for_interval(provider, interval)
    if maximum_age is not None and at < as_of - maximum_age:
        raise HistoricalMarketLookbackUnavailableError()


def _chunks(values: tuple[datetime, ...]) -> tuple[tuple[datetime, ...], ...]:
    return tuple(
        values[index : index + _MAX_REQUEST_TIMESTAMPS]
        for index in range(0, len(values), _MAX_REQUEST_TIMESTAMPS)
    )


def _price_interval(
    provider: HistoricalPriceProvider | None, *, requires_subdaily: bool
) -> HistoricalTimeSeriesInterval:
    if provider is None:
        raise HistoryGenerationBuildError()
    supported = provider.capability.supported_intervals
    if requires_subdaily:
        for candidate in (
            HistoricalTimeSeriesInterval.provider_determined,
            HistoricalTimeSeriesInterval.thirty_minutes,
        ):
            if candidate in supported:
                return candidate
        raise HistoryGenerationBuildError()
    if HistoricalTimeSeriesInterval.daily in supported:
        return HistoricalTimeSeriesInterval.daily
    # The provider interval describes source evidence, not the portfolio layer.
    # Canonical Twelve Data daily bars lack an unambiguous UTC close without an
    # exchange calendar, so use its genuine intraday closes for daily points.
    for candidate in (
        HistoricalTimeSeriesInterval.provider_determined,
        HistoricalTimeSeriesInterval.thirty_minutes,
    ):
        if candidate in supported:
            return candidate
    raise HistoryGenerationBuildError()


def _fx_interval(
    provider: HistoricalExchangeRateProvider | None, *, requires_subdaily: bool
) -> HistoricalTimeSeriesInterval:
    if provider is None:
        raise HistoryGenerationBuildError()
    supported = provider.capability.supported_intervals
    if requires_subdaily:
        for candidate in (
            HistoricalTimeSeriesInterval.provider_determined,
            HistoricalTimeSeriesInterval.thirty_minutes,
        ):
            if candidate in supported:
                return candidate
        raise HistoryGenerationBuildError()
    if HistoricalTimeSeriesInterval.daily in supported:
        return HistoricalTimeSeriesInterval.daily
    for candidate in (
        HistoricalTimeSeriesInterval.provider_determined,
        HistoricalTimeSeriesInterval.thirty_minutes,
    ):
        if candidate in supported:
            return candidate
    raise HistoryGenerationBuildError()


def _account_by_id(scope: FrozenPortfolioReplayInput) -> dict[str, FrozenAccountReplayInput]:
    return {account.account_id: account for account in scope.accounts}


def _listing_by_id(account: FrozenAccountReplayInput) -> dict[str, FrozenListingIdentity]:
    return {identity.listing_id: identity for identity in account.listing_identities}


def _required_currencies(
    state: AccountReplayState,
    listings: Mapping[str, FrozenListingIdentity],
) -> set[str]:
    currencies = {item.currency for item in state.cash_by_currency}
    for holding in state.holdings:
        identity = listings.get(holding.listing_id)
        if identity is None:
            raise HistoryGenerationBuildError()
        currencies.add(identity.price_currency)
        # ``holding.currency`` records the acquisition-price lineage.  It is
        # not itself valued by the snapshot projection: only an explicit cost
        # basis component is converted.  Requesting its FX rate would pass
        # unused evidence to the strict projection and make the whole account
        # valuation fail closed.
        if holding.cost_basis_by_currency is not None:
            currencies.update(currency for currency, _ in holding.cost_basis_by_currency)
    if state.liability is not None:
        currencies.add(state.liability.currency)
    return currencies


class HistoricalMarketAcquirer:
    """Fetch each exact provider identity in bounded groups without fallback."""

    def __init__(
        self,
        *,
        price_providers: Mapping[PriceSource, HistoricalPriceProvider],
        fx_providers: Mapping[ExchangeRateSource, HistoricalExchangeRateProvider],
        source_policy: MarketEvidenceSourcePolicy,
        evidence_policy: MarketEvidencePolicy,
        maximum_parallel_calls: int = _MAX_PARALLEL_CALLS,
    ) -> None:
        if not 1 <= maximum_parallel_calls <= _MAX_PARALLEL_CALLS:
            raise HistoryGenerationBuildError()
        self.price_providers = dict(price_providers)
        self.fx_providers = dict(fx_providers)
        self.source_policy = source_policy
        self.evidence_policy = evidence_policy
        self.maximum_parallel_calls = maximum_parallel_calls

    def subdaily_available_since(
        self, *, scope: FrozenPortfolioReplayInput, as_of: datetime
    ) -> datetime | None:
        """Conservatively bound fine layers by every required source's retention."""
        price_providers = {
            identity.provider: self.price_providers.get(identity.provider)
            for account in scope.accounts
            for identity in account.listing_identities
        }
        fx_provider = self.fx_providers.get(self.source_policy.fx_source)
        cutoffs: list[datetime] = []
        for provider in price_providers.values():
            if provider is None:
                return as_of + timedelta(milliseconds=1)
            try:
                interval = _price_interval(provider, requires_subdaily=True)
            except HistoryGenerationBuildError:
                return as_of + timedelta(milliseconds=1)
            maximum_age = _maximum_age_for_interval(provider, interval)
            if maximum_age is not None:
                cutoffs.append(as_of - maximum_age)
        if fx_provider is not None:
            try:
                interval = _fx_interval(fx_provider, requires_subdaily=True)
            except HistoryGenerationBuildError:
                return as_of + timedelta(milliseconds=1)
            maximum_age = _maximum_age_for_interval(fx_provider, interval)
            if maximum_age is not None:
                cutoffs.append(as_of - maximum_age)
        return max(cutoffs) if cutoffs else None

    async def acquire(
        self,
        *,
        scope: FrozenPortfolioReplayInput,
        states: Mapping[datetime, Mapping[str, AccountReplayState]],
        requested_at: tuple[datetime, ...],
        subdaily_at: tuple[datetime, ...],
    ) -> HistoricalMarketSelection:
        accounts = _account_by_id(scope)
        if subdaily_at != tuple(sorted(set(subdaily_at))) or not set(subdaily_at) <= set(
            requested_at
        ):
            raise HistoryGenerationBuildError()
        subdaily = set(subdaily_at)
        price_times: defaultdict[
            tuple[
                str,
                str,
                str,
                PriceSource,
                str,
                HistoricalTimeSeriesInterval,
            ],
            set[datetime],
        ] = defaultdict(set)
        fx_times: defaultdict[
            tuple[str, str, ExchangeRateSource, HistoricalTimeSeriesInterval],
            set[datetime],
        ] = defaultdict(set)
        price_accounts: defaultdict[
            tuple[str, datetime, HistoricalTimeSeriesInterval], set[str]
        ] = defaultdict(set)
        fx_accounts: defaultdict[
            tuple[str, str, datetime, HistoricalTimeSeriesInterval], dict[str, bool]
        ] = defaultdict(dict)
        snapshot_fx_accounts: defaultdict[
            tuple[str, str, datetime, HistoricalTimeSeriesInterval], set[str]
        ] = defaultdict(set)
        metric_fx_evidence: defaultdict[
            tuple[str, str, datetime, HistoricalTimeSeriesInterval], set[tuple[str, str]]
        ] = defaultdict(set)
        for through in requested_at:
            timestamp_states = states.get(through)
            if timestamp_states is None:
                raise HistoryGenerationBuildError()
            for account_id, state in timestamp_states.items():
                account = accounts.get(account_id)
                if account is None or not state.active:
                    continue
                listings = _listing_by_id(account)
                for holding in state.holdings:
                    identity = listings.get(holding.listing_id)
                    if identity is None:
                        raise HistoryGenerationBuildError()
                    interval = _price_interval(
                        self.price_providers.get(identity.provider),
                        requires_subdaily=through in subdaily,
                    )
                    _require_available(
                        self.price_providers[identity.provider],
                        interval,
                        at=through,
                        as_of=requested_at[-1],
                    )
                    price_times[
                        (
                            identity.asset_id,
                            identity.listing_id,
                            identity.price_currency,
                            identity.provider,
                            identity.provider_symbol,
                            interval,
                        )
                    ].add(through)
                    price_accounts[(identity.listing_id, through, interval)].add(account_id)
                consumed_currencies = _required_currencies(
                    state,
                    listings,
                )
                for currency in consumed_currencies:
                    if currency == scope.base_currency:
                        pass
                    else:
                        interval = _fx_interval(
                            self.fx_providers.get(self.source_policy.fx_source),
                            requires_subdaily=through in subdaily,
                        )
                        _require_available(
                            self.fx_providers[self.source_policy.fx_source],
                            interval,
                            at=through,
                            as_of=requested_at[-1],
                        )
                        pair = (
                            currency,
                            scope.base_currency,
                            self.source_policy.fx_source,
                            interval,
                        )
                        fx_times[pair].add(through)
                        fx_accounts[(currency, scope.base_currency, through, interval)][
                            account_id
                        ] = True
                    for output_currency in {account.account_currency, scope.base_currency}:
                        if currency == output_currency:
                            continue
                        interval = _fx_interval(
                            self.fx_providers.get(self.source_policy.fx_source),
                            requires_subdaily=through in subdaily,
                        )
                        _require_available(
                            self.fx_providers[self.source_policy.fx_source],
                            interval,
                            at=through,
                            as_of=requested_at[-1],
                        )
                        pair = (
                            currency,
                            output_currency,
                            self.source_policy.fx_source,
                            interval,
                        )
                        fx_times[pair].add(through)
                        snapshot_fx_accounts[(currency, output_currency, through, interval)].add(
                            account_id
                        )

        if requested_at:
            metric_as_of = requested_at[-1]
            for account in scope.accounts:
                try:
                    metric_evidence = build_historical_metric_evidence(
                        account_id=account.account_id,
                        account_type=account.account_type,
                        roots=account.roots,
                        as_of=metric_as_of,
                    )
                except AccountSnapshotEvidenceStateError as exc:
                    raise HistoryGenerationBuildError() from exc
                for item in metric_evidence.historical_evidence:
                    for output_currency in {account.account_currency, scope.base_currency}:
                        if item.currency == output_currency:
                            continue
                        interval = _fx_interval(
                            self.fx_providers.get(self.source_policy.fx_source),
                            # Financial metrics use event-date FX.  Request the
                            # stable daily series while retaining the exact event
                            # timestamp as the as-of boundary.  Old intraday FX is
                            # not available from every provider and choosing it
                            # for recent events would make the same rebuild change
                            # once the provider's intraday retention expires.
                            requires_subdaily=False,
                        )
                        _require_available(
                            self.fx_providers[self.source_policy.fx_source],
                            interval,
                            at=item.timestamp,
                            as_of=requested_at[-1],
                        )
                        pair = (
                            item.currency,
                            output_currency,
                            self.source_policy.fx_source,
                            interval,
                        )
                        fx_times[pair].add(item.timestamp)
                        metric_fx_evidence[
                            (item.currency, output_currency, item.timestamp, interval)
                        ].add((account.account_id, item.evidence_id))

        semaphore = asyncio.Semaphore(self.maximum_parallel_calls)

        async def fetch_price(
            requirement: HistoricalPriceRangeRequirement,
        ) -> tuple[HistoricalPriceRangeRequirement, tuple[PriceObservation, ...]]:
            provider = self.price_providers.get(requirement.provider)
            if provider is None:
                raise HistoryGenerationBuildError()
            async with semaphore:
                return requirement, await provider.fetch_range(requirement)

        async def fetch_fx(
            requirement: HistoricalExchangeRateRangeRequirement,
        ) -> tuple[HistoricalExchangeRateRangeRequirement, tuple[ExchangeRateObservation, ...]]:
            provider = self.fx_providers.get(requirement.provider)
            if provider is None:
                raise HistoryGenerationBuildError()
            async with semaphore:
                return requirement, await provider.fetch_range(requirement)

        price_requirements = tuple(
            HistoricalPriceRangeRequirement(
                asset_id=key[0],
                listing_id=key[1],
                listing_currency=key[2],
                provider=key[3],
                provider_symbol=key[4],
                requested_at=chunk,
                interval=key[5],
            )
            for key, times in sorted(price_times.items(), key=lambda item: item[0])
            for chunk in _chunks(tuple(sorted(times)))
        )
        fx_requirements = tuple(
            HistoricalExchangeRateRangeRequirement(
                from_currency=key[0],
                to_currency=key[1],
                provider=key[2],
                requested_at=chunk,
                interval=key[3],
            )
            for key, times in sorted(fx_times.items(), key=lambda item: item[0])
            for chunk in _chunks(tuple(sorted(times)))
        )
        fetched_prices, fetched_rates = await asyncio.gather(
            asyncio.gather(*(fetch_price(item) for item in price_requirements)),
            asyncio.gather(*(fetch_fx(item) for item in fx_requirements)),
        )

        selected_prices: list[SelectedHistoricalPrice] = []
        price_observations: dict[str, PriceObservation] = {}
        listing_lookup = {
            identity.listing_id: identity
            for account in scope.accounts
            for identity in account.listing_identities
        }
        for requirement, candidates in fetched_prices:
            for selection in select_historical_prices(
                requirement, candidates, policy=self.evidence_policy
            ):
                identity = listing_lookup[requirement.listing_id]
                selected_id = price_snapshot_id(selection.observation)
                existing = price_observations.setdefault(selected_id, selection.observation)
                if existing != selection.observation:
                    raise HistoryGenerationBuildError()
                for account_id in sorted(
                    price_accounts[
                        (requirement.listing_id, selection.through, requirement.interval)
                    ]
                ):
                    selected_prices.append(
                        SelectedHistoricalPrice(
                            account_id=account_id,
                            through=selection.through,
                            listing=identity,
                            price_id=selected_id,
                            observation=selection.observation,
                        )
                    )

        selected_rates: list[SelectedHistoricalRate] = []
        selected_snapshot_rates: list[SelectedHistoricalSnapshotRate] = []
        selected_metric_rates: list[SelectedHistoricalMetricRate] = []
        rate_observations: dict[str, ExchangeRateObservation] = {}
        for rate_requirement, rate_candidates in fetched_rates:
            for rate_selection in select_historical_exchange_rates(
                rate_requirement, rate_candidates, policy=self.evidence_policy
            ):
                selected_id = exchange_rate_id(rate_selection.observation)
                existing_rate = rate_observations.setdefault(
                    selected_id, rate_selection.observation
                )
                if existing_rate != rate_selection.observation:
                    raise HistoryGenerationBuildError()
                account_flags = fx_accounts[
                    (
                        rate_requirement.from_currency,
                        rate_requirement.to_currency,
                        rate_selection.through,
                        rate_requirement.interval,
                    )
                ]
                for account_id, consumed in sorted(account_flags.items()):
                    selected_rates.append(
                        SelectedHistoricalRate(
                            account_id=account_id,
                            through=rate_selection.through,
                            rate_id=selected_id,
                            observation=rate_selection.observation,
                            consumed=consumed,
                        )
                    )
                for account_id in sorted(
                    snapshot_fx_accounts[
                        (
                            rate_requirement.from_currency,
                            rate_requirement.to_currency,
                            rate_selection.through,
                            rate_requirement.interval,
                        )
                    ]
                ):
                    selected_snapshot_rates.append(
                        SelectedHistoricalSnapshotRate(
                            account_id=account_id,
                            through=rate_selection.through,
                            output_currency=rate_requirement.to_currency,
                            rate_id=selected_id,
                            observation=rate_selection.observation,
                        )
                    )
                for account_id, evidence_id in sorted(
                    metric_fx_evidence[
                        (
                            rate_requirement.from_currency,
                            rate_requirement.to_currency,
                            rate_selection.through,
                            rate_requirement.interval,
                        )
                    ]
                ):
                    selected_metric_rates.append(
                        SelectedHistoricalMetricRate(
                            account_id=account_id,
                            evidence_id=evidence_id,
                            event_at=rate_selection.through,
                            output_currency=rate_requirement.to_currency,
                            rate_id=selected_id,
                            observation=rate_selection.observation,
                        )
                    )
        return HistoricalMarketSelection(
            prices=tuple(
                sorted(
                    selected_prices, key=lambda item: (item.through, item.account_id, item.price_id)
                )
            ),
            rates=tuple(
                sorted(
                    selected_rates, key=lambda item: (item.through, item.account_id, item.rate_id)
                )
            ),
            price_observations=tuple(
                observation for _, observation in sorted(price_observations.items())
            ),
            rate_observations=tuple(
                observation for _, observation in sorted(rate_observations.items())
            ),
            provider_call_count=len(price_requirements) + len(fx_requirements),
            snapshot_rates=tuple(
                sorted(
                    selected_snapshot_rates,
                    key=lambda item: (
                        item.through,
                        item.account_id,
                        item.output_currency,
                        item.rate_id,
                    ),
                )
            ),
            metric_rates=tuple(
                sorted(
                    selected_metric_rates,
                    key=lambda item: (
                        item.event_at,
                        item.account_id,
                        item.output_currency,
                        item.evidence_id,
                        item.rate_id,
                    ),
                )
            ),
        )


__all__ = [
    "HistoricalMarketAcquirer",
    "HistoricalMarketSelection",
    "SelectedHistoricalMetricRate",
    "SelectedHistoricalPrice",
    "SelectedHistoricalRate",
    "SelectedHistoricalSnapshotRate",
]
