"""Server-owned strict daily-baseline current-value orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.common import QUANTITY
from app.db.models.enums import (
    AccountType,
    AssetType,
    ExchangeRateSource,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.prices import ExchangeRateModel
from app.db.models.snapshots import AccountSnapshotModel
from app.modules.current_value.delta_projection import (
    CurrentDeltaProjectionError,
    CurrentInvestmentEvent,
    CurrentTransaction,
    add_currency_breakdowns,
    apply_cash_transactions,
    apply_investment_cash_transactions,
    apply_investment_events,
)
from app.modules.current_value.models import CurrentPortfolioResult, CurrentValuePlan
from app.modules.current_value.repository import CurrentValueRepository
from app.modules.daily_baselines.service import (
    DailyBaselineAccount,
    DailyBaselineChange,
    DailyBaselineUnavailableError,
    DailySnapshotBaseline,
    DailySnapshotBaselineService,
)
from app.modules.holdings.persistence_projection import ExpectedPersistedHoldingPlan
from app.modules.market_data.factory import create_production_market_evidence_service
from app.modules.market_data.models import (
    ExchangeRateRequirement,
    MarketEvidenceConflictError,
    MarketEvidenceRefreshPlan,
    MarketEvidenceRefreshResult,
    MarketEvidenceStateError,
)
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
)
from app.modules.market_data.requirements import (
    BuildMarketEvidenceRefreshPlanCommand,
    build_price_requirement,
)
from app.modules.market_data.service import RefreshMarketEvidenceCommand
from app.modules.market_data.source_policy import (
    MarketEvidenceSourcePolicy,
    market_evidence_source_policy_from_settings,
)
from app.modules.portfolio_snapshot.aggregate_models import (
    AccountPortfolioPresentationView,
    MultiAccountPortfolioSummary,
    MultiAccountPortfolioView,
)
from app.modules.portfolio_snapshot.aggregation import build_multi_account_portfolio_view
from app.modules.portfolio_snapshot.currency_breakdown import (
    PortfolioCurrencyBreakdownError,
    decode_portfolio_currency_breakdown,
)
from app.modules.portfolio_snapshot.models import (
    AccountType as PortfolioAccountType,
)
from app.modules.portfolio_snapshot.models import (
    AssetType as PortfolioAssetType,
)
from app.modules.portfolio_snapshot.models import (
    PortfolioAccountView,
    PortfolioCurrencyAmount,
    PortfolioPositionView,
    PortfolioSnapshotView,
    PortfolioSummaryView,
)
from app.modules.portfolio_snapshot.models import (
    SnapshotGranularity as PortfolioGranularity,
)
from app.modules.portfolio_snapshot.models import (
    SnapshotSource as PortfolioSource,
)
from app.modules.snapshots.account_projection import (
    AccountSnapshotProjectionInput,
    AccountSnapshotProjectionStateError,
    CashBalanceEvidence,
    CurrencyAmount,
    LiabilityBalanceEvidence,
    SnapshotHoldingEvidence,
    build_account_snapshot_projection,
)
from app.modules.snapshots.evidence_service import (
    required_conversion_pairs,
    select_latest_exchange_rate,
    select_latest_price_evidence,
    select_snapshot_exchange_rates,
    validate_exchange_rate_candidates,
)
from app.modules.snapshots.financial_metrics import (
    AccountSnapshotEvidenceStateError,
    HistoricalMetricEvidence,
    SelectedHistoricalRate,
    build_financial_metrics,
    exact_money,
)
from app.shared.errors import ApplicationError

_CASH_TYPES = {AccountType.bank, AccountType.cash, AccountType.savings, AccountType.credit_card}
_INVESTMENT_TYPES = {AccountType.broker, AccountType.exchange, AccountType.crypto_wallet}
_LIABILITY_TYPES = {AccountType.loan, AccountType.mortgage}


class CurrentValueUnavailableError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="current_value_unavailable",
            message="Current portfolio value cannot be produced from the available evidence.",
            status_code=409,
        )


class _PublicationStateChangedError(RuntimeError):
    """The durable import fence changed between stable current-value reads."""


@dataclass(frozen=True, slots=True)
class ReadCurrentPortfolioCommand:
    principal: AuthenticatedPrincipal


@dataclass(frozen=True, slots=True)
class _PreparedAccount:
    lineage: DailyBaselineAccount
    account: PortfolioAccountView
    primary_baseline: PortfolioSnapshotView
    presentation_baseline: PortfolioSnapshotView
    primary_snapshot: AccountSnapshotModel
    presentation_snapshot: AccountSnapshotModel
    holdings: tuple[ExpectedPersistedHoldingPlan, ...]
    cash_by_currency: tuple[PortfolioCurrencyAmount, ...]
    forward_metrics: tuple[HistoricalMetricEvidence, ...]
    forward_asset_transfer: bool
    liability: LiabilityBalanceModel | None


@dataclass(frozen=True, slots=True)
class _PreparedState:
    baseline: DailySnapshotBaseline
    accounts: tuple[_PreparedAccount, ...]


def _select_account_types(
    state: _PreparedState,
    account_types: frozenset[AccountType] | None,
) -> _PreparedState:
    if account_types is None:
        return state
    return _PreparedState(
        baseline=state.baseline,
        accounts=tuple(
            account for account in state.accounts if account.lineage.account_type in account_types
        ),
    )


def _empty_portfolio(
    *,
    as_of: datetime,
    baseline: DailySnapshotBaseline,
) -> MultiAccountPortfolioView:
    """Represent an authorized user with no accounts in the requested portfolio scope."""

    zero = Decimal(0).quantize(Decimal("0.000001"))
    return MultiAccountPortfolioView(
        timestamp=as_of,
        granularity=PortfolioGranularity.minute,
        currency=baseline.currency,
        calculation_version=baseline.calculation_version,
        summary=MultiAccountPortfolioSummary(
            cash_value=zero,
            cash_by_currency=(),
            investment_value=zero,
            investment_cost_basis=zero,
            liabilities_value=zero,
            total_value=zero,
            net_deposits_value=zero,
            net_deposits_by_currency=(),
            realized_pnl_value=zero,
            unrealized_pnl_value=zero,
            fees_value=zero,
            taxes_value=zero,
            account_count=0,
            position_count=0,
        ),
        accounts=(),
    )


class _MarketService(Protocol):
    async def refresh(
        self,
        command: RefreshMarketEvidenceCommand,
    ) -> MarketEvidenceRefreshResult: ...


class _PlanBuilder(Protocol):
    async def build(
        self,
        command: BuildMarketEvidenceRefreshPlanCommand,
    ) -> MarketEvidenceRefreshPlan: ...


Clock = Callable[[], datetime]
MarketServiceFactory = Callable[[AsyncSession, Settings, _PlanBuilder], _MarketService]


def current_value_timestamp() -> datetime:
    return datetime.now(UTC)


def canonical_current_value_as_of(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise CurrentValueUnavailableError()
    normalized = value if value.tzinfo is None else value.astimezone(UTC).replace(tzinfo=None)
    return normalized.replace(second=0, microsecond=0)


def _production_market_service(
    session: AsyncSession,
    settings: Settings,
    planner: _PlanBuilder,
) -> _MarketService:
    return create_production_market_evidence_service(
        session,
        settings,
        planner=planner,
    )


class _StaticPlanner:
    def __init__(self, plan: MarketEvidenceRefreshPlan) -> None:
        self.plan = plan

    async def build(
        self,
        command: BuildMarketEvidenceRefreshPlanCommand,
    ) -> MarketEvidenceRefreshPlan:
        if (
            not isinstance(command, BuildMarketEvidenceRefreshPlanCommand)
            or command.user_id != self.plan.user_id
            or command.snapshot_timestamp != self.plan.snapshot_timestamp
        ):
            raise MarketEvidenceStateError()
        return self.plan


def _fail() -> CurrentValueUnavailableError:
    return CurrentValueUnavailableError()


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\0" in value:
        raise _fail()
    return value


def _currency(value: object) -> str:
    result = _text(value)
    if len(result) != 3 or not result.isascii() or not result.isalpha() or result != result.upper():
        raise _fail()
    return result


def _money(value: object) -> Decimal:
    try:
        return exact_money(value)
    except AccountSnapshotEvidenceStateError as exc:
        raise _fail() from exc


def _add_money(left: Decimal, right: Decimal) -> Decimal:
    try:
        with localcontext() as context:
            context.prec = 112
            return _money(left + right)
    except (InvalidOperation, OverflowError) as exc:
        raise _fail() from exc


def _add_optional_money(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return _add_money(left, right)


def _subtract_quantity(left: Decimal, right: Decimal) -> Decimal:
    try:
        with localcontext() as context:
            context.prec = 112
            value = left - right
            precision, scale = QUANTITY.precision, QUANTITY.scale
            if precision is None or scale is None:
                raise RuntimeError("Canonical QUANTITY is incomplete.")
            scaled = value.quantize(Decimal(1).scaleb(-scale))
    except (InvalidOperation, OverflowError) as exc:
        raise _fail() from exc
    if value != scaled or not value.is_finite() or abs(value) >= Decimal(10) ** (precision - scale):
        raise _fail()
    return value


def _principal(command: object) -> str:
    if not isinstance(command, ReadCurrentPortfolioCommand):
        raise _fail()
    principal = command.principal
    if not isinstance(principal, AuthenticatedPrincipal):
        raise _fail()
    return _text(principal.user_id)


def _account_view(
    lineage: DailyBaselineAccount,
    baseline: PortfolioSnapshotView,
    *,
    granularity: SnapshotGranularity,
) -> None:
    if (
        baseline.account.account_id != lineage.account_id
        or baseline.account.currency != lineage.account_currency
        or baseline.timestamp.tzinfo is not None
        or baseline.granularity.value != granularity.value
    ):
        raise _fail()


def _baseline_snapshot_rate_ids(
    snapshot: AccountSnapshotModel,
    *,
    source_policy: MarketEvidenceSourcePolicy,
) -> tuple[str, ...]:
    """Validate the immutable FX audit before reusing a baseline scalar.

    The snapshot's JSON is an audit index, not a valuation input.  Its exact
    rate IDs are reloaded below so historical entries (which intentionally do
    not duplicate a source field in v1) are checked against the active source
    policy as well.
    """

    audit = snapshot.exchange_rates
    if not isinstance(audit, dict):
        raise _fail()
    version = audit.get("version")
    snapshot_rates = audit.get("snapshotRates")
    historical_ids = audit.get("historicalRateIds")
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version not in {1, 2}
        or not isinstance(snapshot_rates, list)
        or not isinstance(historical_ids, list)
    ):
        raise _fail()

    snapshot_ids: list[str] = []
    for entry in snapshot_rates:
        if not isinstance(entry, dict):
            raise _fail()
        rate_id = _text(entry.get("rateId"))
        if entry.get("source") != source_policy.fx_source.value:
            raise _fail()
        snapshot_ids.append(rate_id)

    historical: list[str] = []
    for rate_id in historical_ids:
        historical.append(_text(rate_id))

    if version == 2:
        historical_rates = audit.get("historicalRates")
        if not isinstance(historical_rates, list):
            raise _fail()
        parsed_historical_ids: list[str] = []
        for entry in historical_rates:
            if not isinstance(entry, dict):
                raise _fail()
            parsed_historical_ids.append(_text(entry.get("rateId")))
        if set(parsed_historical_ids) != set(historical):
            raise _fail()
    elif "historicalRates" in audit:
        raise _fail()

    if len(set(snapshot_ids)) != len(snapshot_ids) or len(set(historical)) != len(historical):
        raise _fail()
    return tuple(sorted({*snapshot_ids, *historical}))


async def _validate_baseline_market_evidence(
    repository: CurrentValueRepository,
    *,
    primary: PortfolioSnapshotView,
    presentation: PortfolioSnapshotView,
    primary_snapshot: AccountSnapshotModel,
    presentation_snapshot: AccountSnapshotModel,
    source_policy: MarketEvidenceSourcePolicy,
) -> None:
    """Do not combine an old policy's persisted baseline with new evidence."""

    expected_item_counts: dict[str, int] = {}
    snapshots_by_id: dict[str, AccountSnapshotModel] = {}
    for view, snapshot in (
        (primary, primary_snapshot),
        (presentation, presentation_snapshot),
    ):
        if view.snapshot_id != snapshot.id:
            raise _fail()
        prior_count = expected_item_counts.setdefault(snapshot.id, len(view.positions))
        if prior_count != len(view.positions):
            raise _fail()
        snapshots_by_id.setdefault(snapshot.id, snapshot)

    snapshot_ids = tuple(sorted(snapshots_by_id))
    items = await repository.load_snapshot_items_with_assets(snapshot_ids)
    if len(items) != sum(expected_item_counts.values()):
        raise _fail()
    observed_item_counts = {snapshot_id: 0 for snapshot_id in snapshot_ids}
    for item, asset in items:
        if (
            item.snapshot_id not in observed_item_counts
            or item.asset_id != asset.id
            or not isinstance(asset.asset_type, AssetType)
            or not isinstance(item.price_source, PriceSource)
        ):
            raise _fail()
        try:
            expected_source = source_policy.price_source_for(asset.asset_type)
        except ValueError as exc:
            raise _fail() from exc
        if item.price_source is not expected_source:
            raise _fail()
        observed_item_counts[item.snapshot_id] += 1
    if observed_item_counts != expected_item_counts:
        raise _fail()

    rate_ids = tuple(
        sorted(
            {
                rate_id
                for snapshot in snapshots_by_id.values()
                for rate_id in _baseline_snapshot_rate_ids(
                    snapshot,
                    source_policy=source_policy,
                )
            }
        )
    )
    rates = await repository.load_exchange_rates_by_ids(rate_ids)
    if {rate.id for rate in rates} != set(rate_ids):
        raise _fail()
    if any(rate.source is not source_policy.fx_source for rate in rates):
        raise _fail()


def _current_transaction(
    account_id: str, change: DailyBaselineChange, row: object
) -> CurrentTransaction:
    from app.db.models.transactions import TransactionModel

    if (
        not isinstance(row, TransactionModel)
        or row.id != change.entity_id
        or row.account_id != account_id
        or row.date != change.financial_timestamp
        or row.archived_at is not None
        or row.deleted_at is not None
    ):
        raise _fail()
    return CurrentTransaction(
        transaction_id=row.id,
        account_id=row.account_id,
        timestamp=row.date,
        amount=row.amount,
        currency=row.currency,
        transaction_type=row.type,
        classification=row.classification,
    )


def _liability(account_id: str, change: DailyBaselineChange, row: object) -> LiabilityBalanceModel:
    if (
        not isinstance(row, LiabilityBalanceModel)
        or row.id != change.entity_id
        or row.account_id != account_id
        or row.effective_at != change.financial_timestamp
    ):
        raise _fail()
    return row


async def _prepare_account(
    repository: CurrentValueRepository,
    *,
    baseline: DailySnapshotBaseline,
    lineage: DailyBaselineAccount,
    changes: tuple[DailyBaselineChange, ...],
    source_policy: MarketEvidenceSourcePolicy,
) -> _PreparedAccount:
    portfolio_granularity = PortfolioGranularity(baseline.granularity.value)
    primary = await repository.load_baseline_view(
        account_id=lineage.account_id,
        snapshot_id=lineage.primary_snapshot_id,
        timestamp=baseline.timestamp,
        granularity=portfolio_granularity,
        currency=baseline.currency,
        calculation_version=baseline.calculation_version,
    )
    presentation = await repository.load_baseline_view(
        account_id=lineage.account_id,
        snapshot_id=lineage.presentation_snapshot_id,
        timestamp=baseline.timestamp,
        granularity=portfolio_granularity,
        currency=lineage.account_currency,
        calculation_version=baseline.calculation_version,
    )
    _account_view(lineage, primary, granularity=baseline.granularity)
    _account_view(lineage, presentation, granularity=baseline.granularity)
    primary_snapshot = await repository.load_snapshot(lineage.primary_snapshot_id)
    presentation_snapshot = await repository.load_snapshot(lineage.presentation_snapshot_id)
    if primary_snapshot is None or presentation_snapshot is None:
        raise _fail()
    await _validate_baseline_market_evidence(
        repository,
        primary=primary,
        presentation=presentation,
        primary_snapshot=primary_snapshot,
        presentation_snapshot=presentation_snapshot,
        source_policy=source_policy,
    )
    if lineage.account_type in _CASH_TYPES:
        if (
            primary.positions
            or presentation.positions
            or any(change.kind != "transaction" for change in changes)
        ):
            raise _fail()
        transactions_list: list[CurrentTransaction] = []
        for change in changes:
            transactions_list.append(
                _current_transaction(
                    lineage.account_id,
                    change,
                    await repository.load_transaction(change.entity_id),
                )
            )
        transactions = tuple(transactions_list)
        cash = apply_cash_transactions(
            account_id=lineage.account_id,
            baseline=primary.summary.cash_by_currency,
            transactions=transactions,
        )
        holdings: tuple[ExpectedPersistedHoldingPlan, ...] = ()
        metrics: tuple[HistoricalMetricEvidence, ...] = ()
        forward_asset_transfer = False
        liability = None
    elif lineage.account_type in _INVESTMENT_TYPES:
        if any(change.kind not in {"investment_event", "transaction"} for change in changes):
            raise _fail()
        events: list[CurrentInvestmentEvent] = []
        investment_transactions: list[CurrentTransaction] = []
        for change in changes:
            if change.kind == "transaction":
                investment_transactions.append(
                    _current_transaction(
                        lineage.account_id,
                        change,
                        await repository.load_transaction(change.entity_id),
                    )
                )
                continue
            event = await repository.load_investment_event(
                event_id=change.entity_id,
                account_id=lineage.account_id,
            )
            if (
                event is None
                or event.event.event_date != change.financial_timestamp
                or event.event.account_id != lineage.account_id
            ):
                raise _fail()
            events.append(event)
        delta = apply_investment_events(
            account_id=lineage.account_id,
            baseline_positions=primary.positions,
            baseline_cash=primary.summary.cash_by_currency,
            events=tuple(events),
        )
        transaction_delta = apply_investment_cash_transactions(
            account_id=lineage.account_id,
            baseline=delta.cash_by_currency,
            transactions=tuple(investment_transactions),
        )
        holdings = delta.holdings.holdings
        cash = transaction_delta.cash_by_currency
        metrics = tuple(
            sorted(
                (*delta.historical_metrics, *transaction_delta.historical_metrics),
                key=lambda item: (item.timestamp, item.evidence_id),
            )
        )
        forward_asset_transfer = delta.has_asset_transfer
        liability = None
    elif lineage.account_type in _LIABILITY_TYPES:
        if (
            primary.positions
            or presentation.positions
            or any(change.kind != "liability_balance" for change in changes)
        ):
            raise _fail()
        baseline_liability_id = _text(lineage.selected_liability_balance_id)
        baseline_liability = await repository.load_liability(baseline_liability_id)
        if (
            baseline_liability is None
            or baseline_liability.account_id != lineage.account_id
            or baseline_liability.effective_at > baseline.timestamp
        ):
            raise _fail()
        forward_list: list[LiabilityBalanceModel] = []
        for change in changes:
            forward_list.append(
                _liability(
                    lineage.account_id,
                    change,
                    await repository.load_liability(change.entity_id),
                )
            )
        forward = tuple(forward_list)
        eligible = (baseline_liability, *forward)
        latest_time = max(item.effective_at for item in eligible)
        latest = tuple(item for item in eligible if item.effective_at == latest_time)
        if len(latest) != 1:
            raise _fail()
        liability = latest[0]
        cash = ()
        holdings = ()
        metrics = ()
        forward_asset_transfer = False
    else:
        raise _fail()
    return _PreparedAccount(
        lineage=lineage,
        account=primary.account,
        primary_baseline=primary,
        presentation_baseline=presentation,
        primary_snapshot=primary_snapshot,
        presentation_snapshot=presentation_snapshot,
        holdings=holdings,
        cash_by_currency=cash,
        forward_metrics=metrics,
        forward_asset_transfer=forward_asset_transfer,
        liability=liability,
    )


async def _prepare_state(
    repository: CurrentValueRepository,
    baseline: DailySnapshotBaseline,
    *,
    source_policy: MarketEvidenceSourcePolicy,
) -> _PreparedState:
    by_account: dict[str, list[DailyBaselineChange]] = {
        account.account_id: [] for account in baseline.accounts
    }
    for change in baseline.post_baseline_changes:
        if change.account_id not in by_account:
            raise _fail()
        by_account[change.account_id].append(change)
    account_list: list[_PreparedAccount] = []
    for lineage in baseline.accounts:
        account_list.append(
            await _prepare_account(
                repository,
                baseline=baseline,
                lineage=lineage,
                changes=tuple(by_account[lineage.account_id]),
                source_policy=source_policy,
            )
        )
    accounts = tuple(account_list)
    return _PreparedState(baseline=baseline, accounts=accounts)


def _fx_keys(
    source: str,
    target: str,
    through: datetime,
    provider: ExchangeRateSource,
) -> set[tuple[str, str, datetime, ExchangeRateSource]]:
    return {
        (base, quote, through, provider)
        for base, quote in required_conversion_pairs(source, target)
    }


async def _build_market_plan(
    repository: CurrentValueRepository,
    state: _PreparedState,
    *,
    as_of: datetime,
    source_policy: MarketEvidenceSourcePolicy,
) -> MarketEvidenceRefreshPlan:
    holding_accounts: dict[str, str] = {}
    for account in state.accounts:
        for holding in account.holdings:
            current = holding_accounts.get(holding.listing_id)
            if current is None or account.lineage.account_id < current:
                holding_accounts[holding.listing_id] = account.lineage.account_id
    identities = await repository.load_listing_identities(tuple(sorted(holding_accounts)))
    if {listing.id for listing, _, _ in identities} != set(holding_accounts):
        raise _fail()
    prices = tuple(
        sorted(
            (
                build_price_requirement(
                    account_id=holding_accounts[listing.id],
                    listing=listing,
                    asset=asset,
                    aliases=aliases,
                    supported_sources=source_policy.price_sources,
                    through=as_of,
                    source_policy=source_policy,
                )
                for listing, asset, aliases in identities
            ),
            key=lambda item: (
                item.account_id,
                item.asset_id,
                item.listing_id,
                item.provider.value,
                item.provider_symbol,
            ),
        )
    )
    price_by_listing = {item.listing_id: item for item in prices}
    required_fx: set[tuple[str, str, datetime, ExchangeRateSource]] = set()
    for account in state.accounts:
        targets = {state.baseline.currency, account.lineage.account_currency}
        current_currencies = {item.currency for item in account.cash_by_currency}
        if account.liability is not None:
            current_currencies.add(account.liability.currency)
        for holding in account.holdings:
            requirement = price_by_listing.get(holding.listing_id)
            if requirement is None:
                raise _fail()
            current_currencies.update((requirement.listing_currency, holding.currency))
        for source in current_currencies:
            for target in targets:
                required_fx.update(_fx_keys(source, target, as_of, source_policy.fx_source))
        for metric in account.forward_metrics:
            for target in targets:
                required_fx.update(
                    _fx_keys(
                        metric.currency,
                        target,
                        metric.timestamp,
                        source_policy.fx_source,
                    )
                )
    fx = tuple(
        ExchangeRateRequirement(
            from_currency=base,
            to_currency=quote,
            through=through,
            provider=provider,
        )
        for base, quote, through, provider in sorted(
            required_fx,
            key=lambda item: (item[0], item[1], item[2], item[3].value),
        )
    )
    return MarketEvidenceRefreshPlan(
        user_id=state.baseline.user_id,
        output_currency=state.baseline.currency,
        snapshot_timestamp=as_of,
        price_requirements=prices,
        fx_requirements=fx,
    )


def _validate_market_result(result: object, plan: MarketEvidenceRefreshPlan) -> None:
    if (
        not isinstance(result, MarketEvidenceRefreshResult)
        or result.user_id != plan.user_id
        or result.output_currency != plan.output_currency
        or result.snapshot_timestamp != plan.snapshot_timestamp
        or result.required_price_count != len(plan.price_requirements)
        or result.required_fx_count != len(plan.fx_requirements)
        or result.prices_created + result.prices_replayed != len(result.price_ids)
        or result.rates_created + result.rates_replayed != len(result.exchange_rate_ids)
        or len(result.price_ids) > result.required_price_count
        or len(result.exchange_rate_ids) > result.required_fx_count
        or (result.required_price_count == 0) != (len(result.price_ids) == 0)
        or (result.required_fx_count == 0) != (len(result.exchange_rate_ids) == 0)
        or len(set(result.price_ids)) != len(result.price_ids)
        or len(set(result.exchange_rate_ids)) != len(result.exchange_rate_ids)
    ):
        raise _fail()


def _snapshot_holdings(account: _PreparedAccount) -> tuple[SnapshotHoldingEvidence, ...]:
    return tuple(
        SnapshotHoldingEvidence(
            holding_id=f"current:{account.lineage.account_id}:{item.listing_id}",
            account_id=account.lineage.account_id,
            asset_id=item.asset_id,
            listing_id=item.listing_id,
            listing_asset_id=item.asset_id,
            symbol=item.symbol,
            asset_type=item.asset_type,
            quantity=item.quantity,
            average_buy_price=item.avg_buy_price,
            cost_currency=item.currency,
            cost_basis_by_currency=(
                None
                if item.cost_basis_by_currency is None
                else tuple(
                    CurrencyAmount(currency=currency, amount=amount)
                    for currency, amount in item.cost_basis_by_currency
                )
            ),
        )
        for item in account.holdings
    )


def _cash_balances(
    account: _PreparedAccount,
    as_of: datetime,
) -> tuple[CashBalanceEvidence, ...]:
    return tuple(
        CashBalanceEvidence(
            balance_id=f"current:{account.lineage.account_id}:{item.currency}",
            account_id=account.lineage.account_id,
            currency=item.currency,
            amount=item.amount,
            timestamp=as_of,
        )
        for item in account.cash_by_currency
    )


def _baseline_breakdown(
    snapshot: AccountSnapshotModel,
    *,
    field: str,
    scalar: Decimal,
) -> tuple[PortfolioCurrencyAmount, ...]:
    try:
        return decode_portfolio_currency_breakdown(
            getattr(snapshot, field),
            scalar_total=scalar,
            output_currency=snapshot.currency,
        )
    except (AttributeError, PortfolioCurrencyBreakdownError) as exc:
        raise _fail() from exc


def _historical_rates(
    metrics: tuple[HistoricalMetricEvidence, ...],
    *,
    output_currency: str,
    candidates: tuple[ExchangeRateModel, ...],
    policy: MarketEvidencePolicy,
    source_policy: MarketEvidenceSourcePolicy,
) -> tuple[SelectedHistoricalRate, ...]:
    result: list[SelectedHistoricalRate] = []
    for metric in metrics:
        for base, quote in required_conversion_pairs(metric.currency, output_currency):
            selected = select_latest_exchange_rate(
                candidates,
                base_currency=base,
                quote_currency=quote,
                source=source_policy.fx_source,
                through=metric.timestamp,
                policy=policy,
            )
            result.append(
                SelectedHistoricalRate(
                    rate_id=selected.id,
                    evidence_id=metric.evidence_id,
                    base_currency=base,
                    quote_currency=quote,
                    rate=selected.rate,
                    timestamp=selected.date,
                )
            )
    return tuple(result)


def _portfolio_type(value: AccountType) -> PortfolioAccountType:
    return PortfolioAccountType(value.value)


def _portfolio_asset_type(value: AssetType) -> PortfolioAssetType:
    return PortfolioAssetType(value.value)


async def _project_account(
    repository: CurrentValueRepository,
    account: _PreparedAccount,
    *,
    output_currency: str,
    as_of: datetime,
    policy: MarketEvidencePolicy,
    source_policy: MarketEvidenceSourcePolicy,
) -> PortfolioSnapshotView:
    holdings = _snapshot_holdings(account)
    price_candidates = await repository.load_price_candidates(
        tuple(item.listing_id for item in holdings),
        through=as_of,
    )
    prices = tuple(
        select_latest_price_evidence(
            price_candidates,
            holding=holding,
            source=source_policy.price_source_for(holding.asset_type),
            through=as_of,
            policy=policy,
        )
        for holding in holdings
    )
    source_currencies = {
        *(item.currency for item in account.cash_by_currency),
        *(item.currency for item in prices),
        *(item.cost_currency for item in holdings),
    }
    liabilities: tuple[LiabilityBalanceEvidence, ...] = ()
    if account.liability is not None:
        source_currencies.add(account.liability.currency)
        liabilities = (
            LiabilityBalanceEvidence(
                liability_id=account.liability.id,
                account_id=account.liability.account_id,
                currency=account.liability.currency,
                amount=account.liability.total_outstanding,
                timestamp=account.liability.effective_at,
            ),
        )
    required_bases = {
        pair[0]
        for currency in source_currencies | {metric.currency for metric in account.forward_metrics}
        for pair in required_conversion_pairs(currency, output_currency)
    }
    candidates = await repository.load_exchange_rate_candidates(
        tuple(sorted(required_bases)),
        output_currency,
        source=source_policy.fx_source,
        through=as_of,
    )
    validated = validate_exchange_rate_candidates(
        candidates,
        base_currencies=tuple(sorted(required_bases)),
        quote_currency=output_currency,
        source=source_policy.fx_source,
        through=as_of,
    )
    snapshot_rates = select_snapshot_exchange_rates(
        validated,
        source_currencies=source_currencies,
        output_currency=output_currency,
        source=source_policy.fx_source,
        through=as_of,
        policy=policy,
    )
    valuation = build_account_snapshot_projection(
        AccountSnapshotProjectionInput(
            account_id=account.lineage.account_id,
            account_type=account.lineage.account_type,
            account_currency=account.lineage.account_currency,
            output_currency=output_currency,
            snapshot_timestamp=as_of,
            granularity=SnapshotGranularity.minute,
            source=SnapshotSource.price_refresh,
            calculation_version=account.primary_baseline.calculation_version,
            holdings=holdings,
            prices=prices,
            exchange_rates=snapshot_rates,
            cash_balances=_cash_balances(account, as_of),
            liabilities=liabilities,
        )
    )
    forward_metrics = build_financial_metrics(
        valuation=valuation,
        historical_evidence=account.forward_metrics,
        historical_rates=_historical_rates(
            account.forward_metrics,
            output_currency=output_currency,
            candidates=validated,
            policy=policy,
            source_policy=source_policy,
        ),
    )
    baseline = (
        account.primary_baseline
        if output_currency == account.primary_baseline.currency
        else account.presentation_baseline
    )
    baseline_snapshot = (
        account.primary_snapshot
        if output_currency == account.primary_snapshot.currency
        else account.presentation_snapshot
    )
    net_deposits = (
        None
        if account.forward_asset_transfer
        else _add_optional_money(
            baseline.summary.net_deposits_value,
            forward_metrics.net_deposits_value,
        )
    )
    realized = (
        None
        if account.forward_asset_transfer or valuation.investment_cost_basis is None
        else _add_optional_money(
            baseline.summary.realized_pnl_value,
            forward_metrics.realized_pnl_value,
        )
    )
    fees = _add_money(baseline.summary.fees_value, forward_metrics.fees_value)
    taxes = _add_money(baseline.summary.taxes_value, forward_metrics.taxes_value)
    net_deposits_breakdown = (
        None
        if baseline.summary.net_deposits_by_currency is None or net_deposits is None
        else add_currency_breakdowns(
            baseline.summary.net_deposits_by_currency,
            tuple(
                PortfolioCurrencyAmount(currency=item.currency, amount=item.amount)
                for item in forward_metrics.net_deposits_by_currency
            ),
        )
    )
    # Validate hidden cumulative native breakdowns before carrying their
    # scalar authorities forward. They remain server-only in the 0.1 API.
    for field, scalar in (
        ("realized_pnl_by_currency", baseline.summary.realized_pnl_value),
        ("fees_by_currency", baseline.summary.fees_value),
        ("taxes_by_currency", baseline.summary.taxes_value),
    ):
        if scalar is not None:
            _baseline_breakdown(baseline_snapshot, field=field, scalar=scalar)

    metadata_rows = await repository.load_listing_metadata(
        tuple(item.listing_id for item in valuation.items)
    )
    metadata = {listing.id: (listing, asset) for listing, asset in metadata_rows}
    positions: list[PortfolioPositionView] = []
    for item in valuation.items:
        listing_asset = metadata.get(item.listing_id)
        if listing_asset is None:
            raise _fail()
        listing, asset = listing_asset
        if (
            listing.asset_id != item.asset_id
            or asset.id != item.asset_id
            or listing.symbol != item.symbol
            or not isinstance(asset.asset_type, AssetType)
        ):
            raise _fail()
        positions.append(
            PortfolioPositionView(
                listing_id=item.listing_id,
                asset_id=item.asset_id,
                symbol=item.symbol,
                name=_text(asset.name),
                asset_type=_portfolio_asset_type(asset.asset_type),
                quantity=item.quantity,
                price_per_unit=item.price_per_unit,
                price_currency=item.price_currency,
                price_timestamp=item.price_timestamp,
                value=item.value,
                value_currency=output_currency,
                cost_basis=item.cost_basis,
                cost_currency=item.cost_currency,
                unrealized_pnl=(
                    None
                    if item.cost_basis is None
                    else _subtract_quantity(item.value, item.cost_basis)
                ),
                allocation_pct=item.allocation_pct,
                native_value=item.native_value,
                native_value_currency=item.value_currency,
                native_cost_basis=item.native_cost_basis,
                native_cost_currency=item.native_cost_currency,
                native_cost_basis_by_currency=(
                    None
                    if item.native_cost_basis_by_currency is None
                    else tuple(
                        PortfolioCurrencyAmount(currency=value.currency, amount=value.amount)
                        for value in item.native_cost_basis_by_currency
                    )
                ),
                average_buy_price=item.average_buy_price,
                average_buy_price_currency=item.average_buy_price_currency,
            )
        )
    summary = PortfolioSummaryView(
        cash_value=valuation.cash_value,
        cash_by_currency=tuple(
            PortfolioCurrencyAmount(currency=item.currency, amount=item.amount)
            for item in valuation.cash_value_by_currency
        ),
        investment_value=valuation.investment_value,
        investment_cost_basis=valuation.investment_cost_basis,
        liabilities_value=valuation.liabilities_value,
        total_value=valuation.total_value,
        net_deposits_value=net_deposits,
        net_deposits_by_currency=net_deposits_breakdown,
        realized_pnl_value=realized,
        unrealized_pnl_value=forward_metrics.unrealized_pnl_value,
        fees_value=fees,
        taxes_value=taxes,
        position_count=len(positions),
    )
    return PortfolioSnapshotView(
        snapshot_id=baseline.snapshot_id,
        account=PortfolioAccountView(
            account_id=account.account.account_id,
            name=account.account.name,
            account_type=_portfolio_type(account.lineage.account_type),
            currency=account.lineage.account_currency,
        ),
        timestamp=as_of,
        granularity=PortfolioGranularity.minute,
        currency=output_currency,
        source=PortfolioSource.price_refresh,
        calculation_version=baseline.calculation_version,
        summary=summary,
        positions=tuple(positions),
    )


class CurrentValueService:
    """Acquire market evidence, then project current finance without snapshots."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        clock: Clock = current_value_timestamp,
        market_service_factory: MarketServiceFactory = _production_market_service,
    ) -> None:
        self.session = session
        self.settings = settings
        self.clock = clock
        self.market_service_factory = market_service_factory
        self.source_policy = market_evidence_source_policy_from_settings(settings)

    async def read_portfolio(
        self,
        command: ReadCurrentPortfolioCommand,
    ) -> CurrentPortfolioResult:
        return await self._read(command, account_types=None)

    async def read_investment_portfolio(
        self,
        command: ReadCurrentPortfolioCommand,
    ) -> CurrentPortfolioResult:
        """Return only broker, exchange and crypto-wallet accounts for Portfolio."""

        return await self._read(command, account_types=frozenset(_INVESTMENT_TYPES))

    async def _read(
        self,
        command: ReadCurrentPortfolioCommand,
        *,
        account_types: frozenset[AccountType] | None,
    ) -> CurrentPortfolioResult:
        user_id = _principal(command)
        as_of = canonical_current_value_as_of(self.clock())
        baseline_service = DailySnapshotBaselineService(self.session)
        try:
            # A status transition while we build/project a current value must
            # not publish a mixed canonical/import view. One retry handles a
            # normal race; sustained churn returns the standard unavailable
            # response instead of guessing which publication is authoritative.
            for attempt in range(2):
                try:
                    frozen_account_ids = await self._load_active_import_account_ids(user_id)
                    baseline = await baseline_service.select_latest_valid(
                        user_id=user_id,
                        through=as_of,
                        frozen_account_ids=frozen_account_ids,
                    )
                    if account_types is not None and not any(
                        account.account_type in account_types for account in baseline.accounts
                    ):
                        await self._require_idle()
                        return CurrentPortfolioResult(
                            as_of=as_of,
                            baseline_id=baseline.baseline_id,
                            baseline_timestamp=baseline.timestamp,
                            baseline_net_worth_snapshot_id=baseline.net_worth_snapshot_id,
                            portfolio=_empty_portfolio(as_of=as_of, baseline=baseline),
                            account_presentations=(),
                        )
                    plan = await self._build_plan(
                        baseline,
                        as_of=as_of,
                        frozen_account_ids=frozen_account_ids,
                        account_types=account_types,
                    )
                    if plan.market_plan.price_requirements or plan.market_plan.fx_requirements:
                        market_service = self.market_service_factory(
                            self.session,
                            self.settings,
                            _StaticPlanner(plan.market_plan),
                        )
                        try:
                            market_result = await market_service.refresh(
                                RefreshMarketEvidenceCommand(
                                    user_id=user_id,
                                    snapshot_timestamp=as_of,
                                    created_at=as_of,
                                )
                            )
                            _validate_market_result(market_result, plan.market_plan)
                        except MarketEvidenceConflictError:
                            # Provider revisions must not overwrite immutable
                            # evidence. Continue only with the existing
                            # evidence; _project still verifies that it is
                            # complete and within the freshness policy.
                            await self._require_idle()
                    return await self._project(plan, account_types=account_types)
                except _PublicationStateChangedError:
                    if attempt == 0:
                        continue
                    raise _fail() from None
                except DailyBaselineUnavailableError:
                    # A backdated canonical post can arrive after the initial
                    # fence read. Re-read the fence once before declaring the
                    # published baseline unavailable.
                    if attempt == 0:
                        continue
                    raise
            raise _fail()
        except CurrentValueUnavailableError:
            await self._close_transaction()
            raise
        except (
            DailyBaselineUnavailableError,
            CurrentDeltaProjectionError,
            AccountSnapshotProjectionStateError,
            AccountSnapshotEvidenceStateError,
            PortfolioCurrencyBreakdownError,
            MarketEvidenceConflictError,
            MarketEvidenceStateError,
            SQLAlchemyError,
        ) as exc:
            await self._close_transaction()
            raise _fail() from exc

    async def _build_plan(
        self,
        baseline: DailySnapshotBaseline,
        *,
        as_of: datetime,
        frozen_account_ids: tuple[str, ...],
        account_types: frozenset[AccountType] | None,
    ) -> CurrentValuePlan:
        if self.session.in_transaction():
            raise _fail()
        async with self.session.begin():
            repository = CurrentValueRepository(self.session)
            await repository.set_repeatable_read_only()
            active_account_ids = await repository.load_active_import_account_ids(
                reader_user_id=baseline.user_id,
                account_ids=tuple(account.account_id for account in baseline.accounts),
            )
            if active_account_ids != frozen_account_ids:
                raise _PublicationStateChangedError()
            exact = await DailySnapshotBaselineService(self.session).validate_exact_in_transaction(
                baseline_id=baseline.baseline_id,
                user_id=baseline.user_id,
                through=as_of,
                frozen_account_ids=frozen_account_ids,
            )
            if exact != baseline:
                raise _fail()
            state = _select_account_types(
                await _prepare_state(
                    repository,
                    exact,
                    source_policy=self.source_policy,
                ),
                account_types,
            )
            market_plan = await _build_market_plan(
                repository,
                state,
                as_of=as_of,
                source_policy=self.source_policy,
            )
        await self._require_idle()
        return CurrentValuePlan(
            as_of=as_of,
            baseline=baseline,
            market_plan=market_plan,
            frozen_account_ids=frozen_account_ids,
        )

    async def _project(
        self,
        plan: CurrentValuePlan,
        *,
        account_types: frozenset[AccountType] | None,
    ) -> CurrentPortfolioResult:
        if self.session.in_transaction():
            raise _fail()
        async with self.session.begin():
            repository = CurrentValueRepository(self.session)
            await repository.set_repeatable_read_only()
            active_account_ids = await repository.load_active_import_account_ids(
                reader_user_id=plan.baseline.user_id,
                account_ids=tuple(account.account_id for account in plan.baseline.accounts),
            )
            if active_account_ids != plan.frozen_account_ids:
                raise _PublicationStateChangedError()
            baseline = await DailySnapshotBaselineService(
                self.session
            ).validate_exact_in_transaction(
                baseline_id=plan.baseline.baseline_id,
                user_id=plan.baseline.user_id,
                through=plan.as_of,
                frozen_account_ids=plan.frozen_account_ids,
            )
            if baseline != plan.baseline:
                raise _fail()
            state = _select_account_types(
                await _prepare_state(
                    repository,
                    baseline,
                    source_policy=self.source_policy,
                ),
                account_types,
            )
            if (
                await _build_market_plan(
                    repository,
                    state,
                    as_of=plan.as_of,
                    source_policy=self.source_policy,
                )
                != plan.market_plan
            ):
                raise _fail()
            primary_views: list[PortfolioSnapshotView] = []
            presentations: list[AccountPortfolioPresentationView] = []
            for account in state.accounts:
                primary = await _project_account(
                    repository,
                    account,
                    output_currency=baseline.currency,
                    as_of=plan.as_of,
                    policy=DEFAULT_MARKET_EVIDENCE_POLICY,
                    source_policy=self.source_policy,
                )
                presentation = primary
                if account.lineage.account_currency != baseline.currency:
                    presentation = await _project_account(
                        repository,
                        account,
                        output_currency=account.lineage.account_currency,
                        as_of=plan.as_of,
                        policy=DEFAULT_MARKET_EVIDENCE_POLICY,
                        source_policy=self.source_policy,
                    )
                primary_views.append(primary)
                presentations.append(
                    AccountPortfolioPresentationView(
                        primary_snapshot_id=account.lineage.primary_snapshot_id,
                        presentation_snapshot_id=account.lineage.presentation_snapshot_id,
                        currency=account.lineage.account_currency,
                        account=presentation.account,
                        source=presentation.source,
                        summary=presentation.summary,
                        positions=presentation.positions,
                    )
                )
            portfolio = (
                _empty_portfolio(as_of=plan.as_of, baseline=baseline)
                if not primary_views
                else build_multi_account_portfolio_view(tuple(primary_views))
            )
        await self._require_idle()
        return CurrentPortfolioResult(
            as_of=plan.as_of,
            baseline_id=baseline.baseline_id,
            baseline_timestamp=baseline.timestamp,
            baseline_net_worth_snapshot_id=baseline.net_worth_snapshot_id,
            portfolio=portfolio,
            account_presentations=tuple(presentations),
        )

    async def _require_idle(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
            raise RuntimeError("Current-value dependency left an active transaction.")

    async def _close_transaction(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()

    async def _load_active_import_account_ids(self, user_id: str) -> tuple[str, ...]:
        if self.session.in_transaction():
            raise _fail()
        async with self.session.begin():
            account_ids = await CurrentValueRepository(self.session).load_active_import_account_ids(
                reader_user_id=user_id
            )
        await self._require_idle()
        return account_ids
