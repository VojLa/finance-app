"""Read-only persisted evidence selection for exact account snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import (
    AccountType,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    SnapshotGranularity,
    SnapshotSource,
    TransactionClassification,
    TransactionType,
)
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.transactions import TransactionModel
from app.modules.snapshots.account_projection import (
    AccountSnapshotProjectionInput,
    AccountSnapshotProjectionStateError,
    CashBalanceEvidence,
    CurrencyAmount,
    ExpectedAccountSnapshotValuation,
    SelectedExchangeRateEvidence,
    SelectedPriceEvidence,
    SnapshotHoldingEvidence,
    build_account_snapshot_projection,
)
from app.modules.snapshots.evidence_repository import (
    AccountSnapshotEvidenceRepository,
    PersistedHoldingEvidence,
)
from app.modules.snapshots.financial_metrics import (
    AccountSnapshotEvidenceStateError,
    ExactFinancialMetrics,
    HistoricalMetricEvidence,
    HistoricalMetricKind,
    SelectedHistoricalRate,
    build_financial_metrics,
    canonical_currency,
    canonical_timestamp,
    exact_money,
    exact_rate,
)

_CASH_ACCOUNT_TYPES = {AccountType.bank, AccountType.cash, AccountType.savings}
_INVESTMENT_ACCOUNT_TYPES = {
    AccountType.broker,
    AccountType.exchange,
    AccountType.crypto_wallet,
}
_LIABILITY_ACCOUNT_TYPES = {
    AccountType.credit_card,
    AccountType.loan,
    AccountType.mortgage,
}


@dataclass(frozen=True, slots=True)
class BuildAccountSnapshotEvidenceCommand:
    account_id: str
    snapshot_timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    calculation_version: int


class SnapshotMetricUnsupportedReason(StrEnum):
    external_cash_flow_classification_unavailable = "external_cash_flow_classification_unavailable"
    fee_classification_unavailable = "fee_classification_unavailable"
    tax_classification_unavailable = "tax_classification_unavailable"


@dataclass(frozen=True, slots=True)
class ExactSnapshotMetric:
    value: Decimal
    breakdown: tuple[CurrencyAmount, ...] | None


@dataclass(frozen=True, slots=True)
class UnsupportedSnapshotMetric:
    reason: SnapshotMetricUnsupportedReason


type SnapshotFinancialMetric = ExactSnapshotMetric | UnsupportedSnapshotMetric


@dataclass(frozen=True, slots=True)
class CompleteAccountSnapshotEvidence:
    valuation: ExpectedAccountSnapshotValuation
    net_deposits: SnapshotFinancialMetric
    realized_pnl: SnapshotFinancialMetric
    unrealized_pnl: SnapshotFinancialMetric
    fees: SnapshotFinancialMetric
    taxes: SnapshotFinancialMetric
    selected_price_ids: tuple[str, ...]
    selected_snapshot_exchange_rate_ids: tuple[str, ...]
    selected_historical_exchange_rate_ids: tuple[str, ...]


def _fail() -> AccountSnapshotEvidenceStateError:
    return AccountSnapshotEvidenceStateError()


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _select_latest_price(
    candidates: tuple[PriceSnapshotModel, ...],
    *,
    holding: SnapshotHoldingEvidence,
    through: datetime,
) -> SelectedPriceEvidence:
    matching = [
        candidate
        for candidate in candidates
        if candidate.listing_id == holding.listing_id
        and canonical_timestamp(candidate.timestamp) <= through
    ]
    if not matching:
        raise _fail()
    selected_timestamp = max(canonical_timestamp(item.timestamp) for item in matching)
    latest = [item for item in matching if item.timestamp == selected_timestamp]
    if len(latest) != 1:
        raise _fail()
    selected = latest[0]
    if (
        _nonblank(selected.id) == ""
        or selected.asset_id != holding.asset_id
        or selected.listing_id != holding.listing_id
    ):
        raise _fail()
    return SelectedPriceEvidence(
        price_id=selected.id,
        asset_id=selected.asset_id,
        listing_id=selected.listing_id,
        symbol=holding.symbol,
        price=selected.price,
        currency=canonical_currency(selected.currency),
        source=selected.source,
        timestamp=selected.timestamp,
    )


def _select_latest_rate(
    candidates: tuple[ExchangeRateModel, ...],
    *,
    base_currency: str,
    quote_currency: str,
    through: datetime,
) -> ExchangeRateModel:
    matching = [
        candidate
        for candidate in candidates
        if candidate.from_currency == base_currency
        and candidate.to_currency == quote_currency
        and candidate.date <= through
    ]
    if not matching:
        raise _fail()
    selected_timestamp = max(canonical_timestamp(item.date) for item in matching)
    latest = [item for item in matching if item.date == selected_timestamp]
    if len(latest) != 1:
        raise _fail()
    selected = latest[0]
    _nonblank(selected.id)
    exact_rate(selected.rate)
    return selected


def _holding_evidence(
    rows: tuple[PersistedHoldingEvidence, ...],
    *,
    account_id: str,
) -> tuple[SnapshotHoldingEvidence, ...]:
    result: list[SnapshotHoldingEvidence] = []
    listing_ids: set[str] = set()
    for persisted in rows:
        holding, listing, asset = persisted.holding, persisted.listing, persisted.asset
        if (
            holding.account_id != account_id
            or listing is None
            or asset is None
            or holding.asset_id != asset.id
            or holding.listing_id != listing.id
            or listing.asset_id != asset.id
            or holding.symbol != listing.symbol
            or holding.symbol != asset.symbol
            or holding.asset_type is not asset.asset_type
            or holding.listing_id in listing_ids
        ):
            raise _fail()
        listing_ids.add(holding.listing_id)
        result.append(
            SnapshotHoldingEvidence(
                holding_id=_nonblank(holding.id),
                account_id=holding.account_id,
                asset_id=_nonblank(asset.id),
                listing_id=_nonblank(listing.id),
                listing_asset_id=_nonblank(listing.asset_id),
                symbol=_nonblank(holding.symbol),
                asset_type=holding.asset_type,
                quantity=holding.quantity,
                average_buy_price=holding.avg_buy_price,
                cost_currency=canonical_currency(holding.currency),
            )
        )
    return tuple(sorted(result, key=lambda item: (item.listing_id, item.holding_id)))


def _cash_from_transactions(
    transactions: tuple[TransactionModel, ...],
    *,
    account_id: str,
    snapshot_timestamp: datetime,
) -> tuple[CashBalanceEvidence, ...]:
    balances: dict[str, Decimal] = {}
    ids: set[str] = set()
    for transaction in transactions:
        transaction_id = _nonblank(transaction.id)
        currency = canonical_currency(transaction.currency)
        amount = exact_money(transaction.amount)
        if (
            transaction_id in ids
            or transaction.account_id != account_id
            or canonical_timestamp(transaction.date) > snapshot_timestamp
            or transaction.archived_at is not None
            or transaction.deleted_at is not None
            or amount == 0
            or (transaction.type is TransactionType.income and amount < 0)
            or (transaction.type is TransactionType.expense and amount > 0)
            or (
                transaction.type is TransactionType.transfer
                and transaction.classification
                not in {
                    TransactionClassification.internal_transfer,
                    TransactionClassification.investment_transfer,
                    TransactionClassification.cash_exchange,
                    TransactionClassification.credit_card_payment,
                    TransactionClassification.loan_repayment,
                }
            )
        ):
            raise _fail()
        ids.add(transaction_id)
        balances[currency] = exact_money(balances.get(currency, Decimal(0)) + amount)
    return tuple(
        CashBalanceEvidence(
            balance_id=f"transactions:{account_id}:{currency}",
            account_id=account_id,
            currency=currency,
            amount=amount,
            timestamp=snapshot_timestamp,
        )
        for currency, amount in sorted(balances.items())
    )


def _investment_history(
    events: tuple[InvestmentEventModel, ...],
    movements: tuple[InvestmentMovementModel, ...],
    *,
    account_id: str,
    snapshot_timestamp: datetime,
) -> tuple[tuple[CashBalanceEvidence, ...], tuple[HistoricalMetricEvidence, ...]]:
    event_by_id: dict[str, InvestmentEventModel] = {}
    for event in events:
        event_id = _nonblank(event.id)
        if (
            event_id in event_by_id
            or event.account_id != account_id
            or canonical_timestamp(event.date) > snapshot_timestamp
            or event.archived_at is not None
            or event.deleted_at is not None
            or (event.realized_pnl is None) != (event.realized_pnl_currency is None)
        ):
            raise _fail()
        event_by_id[event_id] = event

    cash: dict[str, Decimal] = {}
    metrics: list[HistoricalMetricEvidence] = []
    movement_ids: set[str] = set()
    grouped: dict[str, list[InvestmentMovementModel]] = {event_id: [] for event_id in event_by_id}
    for movement in movements:
        movement_id = _nonblank(movement.id)
        movement_event = event_by_id.get(movement.event_id)
        if (
            movement_id in movement_ids
            or movement_event is None
            or movement.account_id != account_id
            or movement.quantity <= 0
        ):
            raise _fail()
        movement_ids.add(movement_id)
        grouped[movement_event.id].append(movement)
        if movement.kind not in {
            InvestmentMovementKind.asset,
            InvestmentMovementKind.cash,
            InvestmentMovementKind.fee,
            InvestmentMovementKind.tax,
        }:
            raise _fail()
        if movement.kind is InvestmentMovementKind.asset:
            continue
        currency = canonical_currency(movement.currency)
        amount = exact_money(movement.quantity)
        if movement.value_amount is not None and (
            exact_money(movement.value_amount) != amount
            or canonical_currency(movement.value_currency) != currency
        ):
            raise _fail()
        signed = amount if movement.direction is MovementDirection.incoming else -amount
        cash[currency] = exact_money(cash.get(currency, Decimal(0)) + signed)
        if movement.kind in {InvestmentMovementKind.fee, InvestmentMovementKind.tax}:
            if movement.direction is not MovementDirection.outgoing:
                raise _fail()
            metrics.append(
                HistoricalMetricEvidence(
                    evidence_id=f"movement:{movement_id}",
                    timestamp=movement_event.date,
                    kind=(
                        HistoricalMetricKind.fee
                        if movement.kind is InvestmentMovementKind.fee
                        else HistoricalMetricKind.tax
                    ),
                    currency=currency,
                    amount=amount,
                )
            )
        elif movement_event.type in {
            InvestmentEventType.cash_deposit,
            InvestmentEventType.cash_withdrawal,
        }:
            expected = (
                MovementDirection.incoming
                if movement_event.type is InvestmentEventType.cash_deposit
                else MovementDirection.outgoing
            )
            if movement.direction is not expected:
                raise _fail()
            metrics.append(
                HistoricalMetricEvidence(
                    evidence_id=f"deposit:{movement_id}",
                    timestamp=movement_event.date,
                    kind=HistoricalMetricKind.net_deposit,
                    currency=currency,
                    amount=amount if expected is MovementDirection.incoming else -amount,
                )
            )

    for event in events:
        event_movements = grouped[event.id]
        assets = [
            movement
            for movement in event_movements
            if movement.kind is InvestmentMovementKind.asset
        ]
        cash_movements = [
            movement for movement in event_movements if movement.kind is InvestmentMovementKind.cash
        ]
        fees = [
            movement for movement in event_movements if movement.kind is InvestmentMovementKind.fee
        ]
        taxes = [
            movement for movement in event_movements if movement.kind is InvestmentMovementKind.tax
        ]
        if not event_movements or len(fees) > 1 or len(taxes) > 1:
            raise _fail()
        if event.type is InvestmentEventType.trade:
            if (
                len(assets) != 1
                or len(cash_movements) != 1
                or assets[0].direction is cash_movements[0].direction
            ):
                raise _fail()
        elif event.type in {
            InvestmentEventType.cash_deposit,
            InvestmentEventType.cash_withdrawal,
            InvestmentEventType.interest,
            InvestmentEventType.dividend,
        }:
            if assets or len(cash_movements) != 1:
                raise _fail()
        elif event.type is InvestmentEventType.currency_conversion:
            if (
                assets
                or len(cash_movements) != 2
                or {movement.direction for movement in cash_movements}
                != {MovementDirection.incoming, MovementDirection.outgoing}
            ):
                raise _fail()
        elif event.type is InvestmentEventType.fee:
            if assets or cash_movements or len(fees) != 1:
                raise _fail()
        elif event.type is not InvestmentEventType.asset_transfer:
            raise _fail()
        if event.type is InvestmentEventType.asset_transfer:
            # Persisted history has no counter-account/externality identity.
            raise _fail()
        if event.realized_pnl is not None:
            if (
                event.type is not InvestmentEventType.trade
                or len(assets) != 1
                or assets[0].direction is not MovementDirection.outgoing
            ):
                raise _fail()
            metrics.append(
                HistoricalMetricEvidence(
                    evidence_id=f"realized:{event.id}",
                    timestamp=event.date,
                    kind=HistoricalMetricKind.realized_pnl,
                    currency=canonical_currency(event.realized_pnl_currency),
                    amount=exact_money(event.realized_pnl),
                )
            )

    balances = tuple(
        CashBalanceEvidence(
            balance_id=f"movements:{account_id}:{currency}",
            account_id=account_id,
            currency=currency,
            amount=amount,
            timestamp=snapshot_timestamp,
        )
        for currency, amount in sorted(cash.items())
    )
    return balances, tuple(sorted(metrics, key=lambda item: (item.timestamp, item.evidence_id)))


class AccountSnapshotEvidenceService:
    """Build complete immutable evidence without owning the transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: AccountSnapshotEvidenceRepository | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or AccountSnapshotEvidenceRepository(session)

    async def build(
        self,
        command: BuildAccountSnapshotEvidenceCommand,
    ) -> CompleteAccountSnapshotEvidence:
        try:
            if not isinstance(command, BuildAccountSnapshotEvidenceCommand):
                raise _fail()
            account_id = _nonblank(command.account_id)
            snapshot_timestamp = canonical_timestamp(command.snapshot_timestamp)
            if (
                not isinstance(command.granularity, SnapshotGranularity)
                or not isinstance(command.source, SnapshotSource)
                or not isinstance(command.calculation_version, int)
                or isinstance(command.calculation_version, bool)
                or command.calculation_version <= 0
            ):
                raise _fail()
            account = await self.repository.load_account(account_id)
            if account is None or account.is_archived or account.archived_at is not None:
                raise _fail()
            output_currency = canonical_currency(account.currency)
            if account.type in _LIABILITY_ACCOUNT_TYPES:
                # No persisted opening balance or dedicated liability balance exists.
                raise _fail()
            if account.type not in _CASH_ACCOUNT_TYPES | _INVESTMENT_ACCOUNT_TYPES:
                raise _fail()

            persisted_holdings = await self.repository.load_holdings(account_id)
            holdings = _holding_evidence(persisted_holdings, account_id=account_id)
            if account.type in _CASH_ACCOUNT_TYPES and holdings:
                raise _fail()

            if account.type in _CASH_ACCOUNT_TYPES:
                transactions = await self.repository.load_active_transactions(
                    account_id,
                    through=snapshot_timestamp,
                )
                cash_balances = _cash_from_transactions(
                    transactions,
                    account_id=account_id,
                    snapshot_timestamp=snapshot_timestamp,
                )
                historical_evidence: tuple[HistoricalMetricEvidence, ...] = ()
            else:
                events = await self.repository.load_active_events(
                    account_id,
                    through=snapshot_timestamp,
                )
                movements = await self.repository.load_active_movements(
                    account_id,
                    through=snapshot_timestamp,
                )
                cash_balances, historical_evidence = _investment_history(
                    events,
                    movements,
                    account_id=account_id,
                    snapshot_timestamp=snapshot_timestamp,
                )

            price_candidates = await self.repository.load_price_candidates(
                tuple(item.listing_id for item in holdings),
                through=snapshot_timestamp,
            )
            prices = tuple(
                _select_latest_price(
                    price_candidates,
                    holding=holding,
                    through=snapshot_timestamp,
                )
                for holding in holdings
            )

            snapshot_currencies = {
                *(item.currency for item in prices),
                *(item.cost_currency for item in holdings),
                *(item.currency for item in cash_balances),
            } - {output_currency}
            historical_currencies = {item.currency for item in historical_evidence} - {
                output_currency
            }
            rate_candidates = await self.repository.load_exchange_rate_candidates(
                tuple(sorted(snapshot_currencies | historical_currencies)),
                output_currency,
                through=snapshot_timestamp,
            )
            snapshot_rates: list[SelectedExchangeRateEvidence] = []
            for currency in sorted(snapshot_currencies):
                selected = _select_latest_rate(
                    rate_candidates,
                    base_currency=currency,
                    quote_currency=output_currency,
                    through=snapshot_timestamp,
                )
                snapshot_rates.append(
                    SelectedExchangeRateEvidence(
                        rate_id=selected.id,
                        base_currency=currency,
                        quote_currency=output_currency,
                        rate=selected.rate,
                        source=selected.source,
                        timestamp=selected.date,
                    )
                )
            historical_rates: list[SelectedHistoricalRate] = []
            for evidence in historical_evidence:
                if evidence.currency == output_currency:
                    continue
                selected = _select_latest_rate(
                    rate_candidates,
                    base_currency=evidence.currency,
                    quote_currency=output_currency,
                    through=evidence.timestamp,
                )
                historical_rates.append(
                    SelectedHistoricalRate(
                        rate_id=selected.id,
                        evidence_id=evidence.evidence_id,
                        base_currency=evidence.currency,
                        quote_currency=output_currency,
                        rate=selected.rate,
                        timestamp=selected.date,
                    )
                )

            valuation = build_account_snapshot_projection(
                AccountSnapshotProjectionInput(
                    account_id=account_id,
                    account_type=account.type,
                    account_currency=output_currency,
                    output_currency=output_currency,
                    snapshot_timestamp=snapshot_timestamp,
                    granularity=command.granularity,
                    source=command.source,
                    calculation_version=command.calculation_version,
                    holdings=holdings,
                    prices=prices,
                    exchange_rates=tuple(snapshot_rates),
                    cash_balances=cash_balances,
                    liabilities=(),
                )
            )
            if account.type in _CASH_ACCOUNT_TYPES:
                structural_zero = ExactSnapshotMetric(value=Decimal(0), breakdown=())
                net_deposits: SnapshotFinancialMetric = UnsupportedSnapshotMetric(
                    SnapshotMetricUnsupportedReason.external_cash_flow_classification_unavailable
                )
                realized_pnl: SnapshotFinancialMetric = structural_zero
                unrealized_pnl: SnapshotFinancialMetric = structural_zero
                fees: SnapshotFinancialMetric = UnsupportedSnapshotMetric(
                    SnapshotMetricUnsupportedReason.fee_classification_unavailable
                )
                taxes: SnapshotFinancialMetric = UnsupportedSnapshotMetric(
                    SnapshotMetricUnsupportedReason.tax_classification_unavailable
                )
                selected_historical_rate_ids: tuple[str, ...] = ()
            else:
                metrics: ExactFinancialMetrics = build_financial_metrics(
                    valuation=valuation,
                    historical_evidence=historical_evidence,
                    historical_rates=tuple(historical_rates),
                )
                net_deposits = ExactSnapshotMetric(
                    value=metrics.net_deposits_value,
                    breakdown=metrics.net_deposits_by_currency,
                )
                realized_pnl = ExactSnapshotMetric(
                    value=metrics.realized_pnl_value,
                    breakdown=metrics.realized_pnl_by_currency,
                )
                unrealized_pnl = ExactSnapshotMetric(
                    value=metrics.unrealized_pnl_value,
                    breakdown=metrics.unrealized_pnl_by_currency,
                )
                fees = ExactSnapshotMetric(
                    value=metrics.fees_value,
                    breakdown=metrics.fees_by_currency,
                )
                taxes = ExactSnapshotMetric(
                    value=metrics.taxes_value,
                    breakdown=metrics.taxes_by_currency,
                )
                selected_historical_rate_ids = metrics.selected_historical_rate_ids
            return CompleteAccountSnapshotEvidence(
                valuation=valuation,
                net_deposits=net_deposits,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                fees=fees,
                taxes=taxes,
                selected_price_ids=tuple(sorted(item.price_id for item in prices)),
                selected_snapshot_exchange_rate_ids=tuple(
                    sorted(item.rate_id for item in snapshot_rates)
                ),
                selected_historical_exchange_rate_ids=selected_historical_rate_ids,
            )
        except AccountSnapshotEvidenceStateError:
            raise
        except AccountSnapshotProjectionStateError as exc:
            raise _fail() from exc
