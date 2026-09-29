"""Pure chronological replay of canonical financial roots."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.db.models.common import MONEY, QUANTITY
from app.db.models.enums import (
    AccountType,
    AssetType,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    TransactionClassification,
    TransactionType,
)
from app.modules.holdings.persistence_projection import (
    ExpectedPersistedHoldingPlan,
    HoldingPersistenceEvent,
    HoldingPersistenceMovement,
    HoldingProjectionStateError,
    build_holding_delta_projection,
)
from app.modules.portfolio_history_rebuild.models import (
    AccountReplayState,
    CurrencyAmount,
    InvestmentEventRoot,
    LiabilityBalanceRoot,
    LiabilityReplayState,
    PortfolioHistoryReplayError,
    ReplayCursor,
    ReplayMetrics,
    ReplayRoot,
    ReplayRootKind,
    TransactionRoot,
)
from app.modules.portfolio_history_rebuild.ordering import (
    canonical_roots,
    root_entity_id,
    root_kind,
    root_timestamp,
)
from app.shared.canonical_arithmetic import CanonicalArithmeticError, canonical_rounded

_CASH_TYPES = {
    AccountType.bank,
    AccountType.cash,
    AccountType.savings,
    AccountType.credit_card,
}
_INVESTMENT_TYPES = {AccountType.broker, AccountType.exchange, AccountType.crypto_wallet}
_LIABILITY_TYPES = {AccountType.loan, AccountType.mortgage}
_TRANSFER_CLASSIFICATIONS = {
    TransactionClassification.internal_transfer,
    TransactionClassification.investment_transfer,
    TransactionClassification.loan_given,
    TransactionClassification.loan_received,
    TransactionClassification.refund,
    TransactionClassification.cash_exchange,
    TransactionClassification.credit_card_payment,
    TransactionClassification.loan_repayment,
}


def _fail(message: str) -> PortfolioHistoryReplayError:
    return PortfolioHistoryReplayError(message)


def _id(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail("Canonical identifiers must be non-empty and trimmed.")
    return value


def _timestamp(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is not None:
        raise _fail("Canonical timestamps must be naive UTC values.")
    if value.microsecond % 1000:
        raise _fail("Canonical timestamps must use millisecond precision.")
    return value


def _currency(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 3
        or not value.isascii()
        or not value.isalpha()
        or value != value.upper()
    ):
        raise _fail("Canonical currencies must be uppercase ISO-like codes.")
    return value


def _money(value: object, *, nonnegative: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise _fail("Canonical money must be a finite Decimal.")
    precision, scale = MONEY.precision, MONEY.scale
    if precision is None or scale is None:
        raise RuntimeError("Canonical MONEY must define precision and scale.")
    try:
        scaled = value.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation as exc:
        raise _fail("Canonical money has invalid scale.") from exc
    if value != scaled or abs(value) >= Decimal(10) ** (precision - scale):
        raise _fail("Canonical money is outside MONEY(18,6).")
    if nonnegative and value < 0:
        raise _fail("Canonical liability amounts cannot be negative.")
    return value


def _quantity(value: object, *, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise _fail("Canonical quantity must be a finite Decimal.")
    precision, scale = QUANTITY.precision, QUANTITY.scale
    if precision is None or scale is None:
        raise RuntimeError("Canonical QUANTITY must define precision and scale.")
    try:
        scaled = value.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation as exc:
        raise _fail("Canonical quantity has invalid scale.") from exc
    if (
        value != scaled
        or abs(value) >= Decimal(10) ** (precision - scale)
        or (positive and value <= 0)
    ):
        raise _fail("Canonical quantity is outside QUANTITY(28,10).")
    return value


def _add_money(left: Decimal, right: Decimal) -> Decimal:
    try:
        return canonical_rounded(left + right, MONEY)
    except CanonicalArithmeticError as exc:
        raise _fail("Canonical money total overflowed.") from exc


def _amounts(values: tuple[CurrencyAmount, ...]) -> dict[str, Decimal]:
    if not isinstance(values, tuple):
        raise _fail("Replay currency totals must be an immutable tuple.")
    result: dict[str, Decimal] = {}
    for value in values:
        if not isinstance(value, CurrencyAmount):
            raise _fail("Replay currency totals contain an invalid item.")
        currency = _currency(value.currency)
        if currency in result:
            raise _fail("Duplicate currency in replay state.")
        result[currency] = _money(value.amount)
    return result


def _frozen_amounts(values: dict[str, Decimal]) -> tuple[CurrencyAmount, ...]:
    return tuple(
        CurrencyAmount(currency, amount)
        for currency, amount in sorted(values.items())
        if amount != 0
    )


def _validate_frozen_amounts(values: tuple[CurrencyAmount, ...]) -> None:
    if _frozen_amounts(_amounts(values)) != values:
        raise _fail("Replay currency totals are not in canonical sorted form.")


def _add(values: dict[str, Decimal], currency: str, amount: Decimal) -> None:
    values[currency] = _add_money(values.get(currency, Decimal("0.000000")), amount)


def _signed(direction: MovementDirection, amount: Decimal) -> Decimal:
    if direction is MovementDirection.incoming:
        return amount
    if direction is MovementDirection.outgoing:
        return -amount
    raise _fail("Unknown investment movement direction.")


def _validate_account(state: AccountReplayState) -> None:
    _id(state.account_id)
    _currency(state.account_currency)
    if not isinstance(state.account_type, AccountType):
        raise _fail("Unknown account type.")
    if not isinstance(state.active, bool):
        raise _fail("Replay active flag must be a boolean.")
    if state.through is not None:
        _timestamp(state.through)
    if state.cursor is not None:
        if not isinstance(state.cursor, ReplayCursor) or not isinstance(
            state.cursor.kind, ReplayRootKind
        ):
            raise _fail("Replay cursor is invalid.")
        _timestamp(state.cursor.timestamp)
        _id(state.cursor.entity_id)
        if state.through != state.cursor.timestamp:
            raise _fail("Replay through timestamp and cursor must agree.")
    if state.active and (state.through is None or state.cursor is None):
        raise _fail("An active account requires a complete replay cursor.")
    if not isinstance(state.metrics, ReplayMetrics):
        raise _fail("Replay metrics are invalid.")
    _validate_frozen_amounts(state.cash_by_currency)
    _validate_frozen_amounts(state.metrics.net_deposits)
    _validate_frozen_amounts(state.metrics.realized_pnl)
    _validate_frozen_amounts(state.metrics.fees)
    _validate_frozen_amounts(state.metrics.taxes)
    if not isinstance(state.metrics.has_asset_transfer, bool):
        raise _fail("Replay transfer state is invalid.")
    if not isinstance(state.holdings, tuple) or any(
        not isinstance(holding, ExpectedPersistedHoldingPlan) for holding in state.holdings
    ):
        raise _fail("Replay holdings are invalid.")
    try:
        validated_holdings = build_holding_delta_projection(
            account_id=state.account_id,
            baseline_holdings=state.holdings,
            events=(),
        ).holdings
    except HoldingProjectionStateError as exc:
        raise _fail("Replay holdings violate the canonical holding projection.") from exc
    if validated_holdings != state.holdings:
        raise _fail("Replay holdings are not in canonical persistence form.")
    if state.account_type in _CASH_TYPES:
        if state.holdings or state.liability is not None or state.metrics != ReplayMetrics():
            raise _fail("Cash-like accounts contain investment or liability state.")
        expected_cursor_kinds = {ReplayRootKind.transaction}
    elif state.account_type in _INVESTMENT_TYPES:
        if state.liability is not None:
            raise _fail("Investment accounts cannot contain liability state.")
        expected_cursor_kinds = {ReplayRootKind.transaction, ReplayRootKind.investment_event}
    elif state.account_type in _LIABILITY_TYPES:
        if state.cash_by_currency or state.holdings or state.metrics != ReplayMetrics():
            raise _fail("Liability accounts contain cash or investment state.")
        if state.active and state.liability is None:
            raise _fail("An active liability account requires a balance observation.")
        expected_cursor_kinds = {ReplayRootKind.liability_balance}
    else:  # pragma: no cover - exhaustive guard for future enum members
        raise _fail("Unknown account type.")
    if state.cursor is not None and state.cursor.kind not in expected_cursor_kinds:
        raise _fail("Replay cursor kind does not match the account domain.")
    if state.liability is not None:
        liability = state.liability
        if not isinstance(liability, LiabilityReplayState):
            raise _fail("Replay liability state is invalid.")
        _id(liability.balance_id)
        _timestamp(liability.effective_at)
        if liability.currency != state.account_currency:
            raise _fail("Replay liability currency must equal the account currency.")
        principal = _money(liability.outstanding_principal, nonnegative=True)
        interest = _money(liability.accrued_interest, nonnegative=True)
        fees = _money(liability.fees_outstanding, nonnegative=True)
        if liability.total_outstanding != _add_money(_add_money(principal, interest), fees):
            raise _fail("Replay liability total does not match its components.")
        if state.through is not None and liability.effective_at > state.through:
            raise _fail("Replay liability observation is newer than the cursor.")
        if state.cursor is not None and (
            liability.effective_at != state.cursor.timestamp
            or liability.balance_id != state.cursor.entity_id
        ):
            raise _fail("Replay liability state does not match its cursor identity.")
    if not state.active and (
        state.through is not None
        or state.cursor is not None
        or state.cash_by_currency
        or state.holdings
        or state.liability is not None
        or state.metrics != ReplayMetrics()
    ):
        raise _fail("An inactive account must be structurally absent.")


def _validate_root_common(state: AccountReplayState, root: ReplayRoot) -> None:
    if _id(root.account_id) != state.account_id:
        raise _fail("Replay root belongs to a different account.")
    _id(root_entity_id(root))
    _timestamp(root_timestamp(root))
    if isinstance(root, TransactionRoot):
        _money(root.amount)
        _currency(root.currency)
        if not isinstance(root.transaction_type, TransactionType) or not isinstance(
            root.classification, TransactionClassification
        ):
            raise _fail("Transaction type and classification are invalid.")
    elif isinstance(root, InvestmentEventRoot):
        if not isinstance(root.event_type, InvestmentEventType):
            raise _fail("Investment event type is invalid.")
        if root.external_id is not None:
            _id(root.external_id)
        if not isinstance(root.movements, tuple) or not root.movements:
            raise _fail("Investment movements must be a non-empty immutable tuple.")
        movement_ids: set[str] = set()
        for movement in root.movements:
            if not isinstance(movement, HoldingPersistenceMovement):
                raise _fail("Investment event contains an invalid movement.")
            movement_id = _id(movement.movement_id)
            if movement_id in movement_ids:
                raise _fail("Investment event contains duplicate movement identities.")
            movement_ids.add(movement_id)
            if (
                _id(movement.event_id) != root.event_id
                or _id(movement.account_id) != root.account_id
            ):
                raise _fail("Investment movement belongs to a different root.")
            if not isinstance(movement.kind, InvestmentMovementKind) or not isinstance(
                movement.direction, MovementDirection
            ):
                raise _fail("Investment movement kind or direction is invalid.")
            if movement.kind is InvestmentMovementKind.asset:
                _quantity(movement.quantity, positive=True)
                asset_id = _id(movement.asset_id)
                _id(movement.listing_id)
                if _id(movement.listing_asset_id) != asset_id:
                    raise _fail("Investment listing belongs to a different asset.")
                symbol = _id(movement.source_symbol)
                if symbol != symbol.upper() or movement.currency != symbol:
                    raise _fail("Investment asset symbol identity is invalid.")
                if not isinstance(movement.source_asset_type, AssetType):
                    raise _fail("Investment asset type is invalid.")
                _currency(movement.listing_currency)
            else:
                _money(movement.quantity)
            if movement.kind is InvestmentMovementKind.tax:
                if (
                    movement.direction is not MovementDirection.outgoing
                    or movement.quantity <= 0
                    or movement.price_per_unit is not None
                    or movement.value_amount != movement.quantity
                    or movement.value_currency != movement.currency
                    or any(
                        value is not None
                        for value in (
                            movement.asset_id,
                            movement.listing_id,
                            movement.listing_asset_id,
                            movement.source_symbol,
                            movement.source_asset_type,
                        )
                    )
                ):
                    raise _fail("Tax movement is not canonical cash evidence.")
                _currency(movement.currency)
        if (root.realized_pnl is None) != (root.realized_pnl_currency is None):
            raise _fail("Realized P/L amount and currency must be present together.")
        if root.realized_pnl is not None:
            _money(root.realized_pnl)
            _currency(root.realized_pnl_currency)
    elif isinstance(root, LiabilityBalanceRoot):
        _currency(root.currency)
        _money(root.outstanding_principal, nonnegative=True)
        _money(root.accrued_interest, nonnegative=True)
        _money(root.fees_outstanding, nonnegative=True)


def _apply_transaction(state: AccountReplayState, root: TransactionRoot) -> AccountReplayState:
    amount = _money(root.amount)
    currency = _currency(root.currency)
    cash = _amounts(state.cash_by_currency)
    if state.account_type in _INVESTMENT_TYPES:
        supported_cash_flow = (
            (
                root.transaction_type is TransactionType.transfer
                and root.classification is TransactionClassification.investment_transfer
            )
            or (
                root.transaction_type is TransactionType.income
                and root.classification is TransactionClassification.real_income
                and amount > 0
            )
            or (
                root.transaction_type is TransactionType.expense
                and root.classification is TransactionClassification.real_expense
                and amount < 0
            )
        )
        if not supported_cash_flow or amount == 0:
            raise _fail("Investment transactions require a supported cash-flow classification.")
        _add(cash, currency, amount)
        net_deposits = _amounts(state.metrics.net_deposits)
        _add(net_deposits, currency, amount)
        return replace(
            state,
            cash_by_currency=_frozen_amounts(cash),
            metrics=ReplayMetrics(
                net_deposits=_frozen_amounts(net_deposits),
                realized_pnl=state.metrics.realized_pnl,
                fees=state.metrics.fees,
                taxes=state.metrics.taxes,
                has_asset_transfer=state.metrics.has_asset_transfer,
            ),
        )
    if state.account_type not in _CASH_TYPES:
        raise _fail("Transaction roots are valid only for cash-like accounts.")
    if root.transaction_type is TransactionType.income and amount <= 0:
        raise _fail("Income must be positive.")
    if root.transaction_type is TransactionType.expense and amount >= 0:
        raise _fail("Expense must be negative.")
    if root.transaction_type is TransactionType.transfer:
        if root.classification not in _TRANSFER_CLASSIFICATIONS or amount == 0:
            raise _fail("Transfer requires a transfer classification and non-zero amount.")
    elif root.transaction_type is TransactionType.income:
        if root.classification is not TransactionClassification.real_income:
            raise _fail("Income requires the real-income classification.")
    elif root.classification is not TransactionClassification.real_expense:
        raise _fail("Expense requires the real-expense classification.")
    _add(cash, currency, amount)
    return replace(state, cash_by_currency=_frozen_amounts(cash))


def _holding_event(root: InvestmentEventRoot) -> HoldingPersistenceEvent:
    # Tax is cash evidence, not a supported cost-position leg. The established
    # holding projection remains the sole owner of asset quantity and cost basis.
    movements = tuple(
        movement for movement in root.movements if movement.kind is not InvestmentMovementKind.tax
    )
    return HoldingPersistenceEvent(
        event_id=root.event_id,
        account_id=root.account_id,
        event_type=root.event_type,
        event_date=root.event_date,
        external_id=root.external_id,
        movements=movements,
    )


def _apply_investment(
    state: AccountReplayState, roots: tuple[InvestmentEventRoot, ...]
) -> AccountReplayState:
    if state.account_type not in _INVESTMENT_TYPES:
        raise _fail("Investment roots are valid only for investment accounts.")
    cash = _amounts(state.cash_by_currency)
    net_deposits = _amounts(state.metrics.net_deposits)
    realized_pnl = _amounts(state.metrics.realized_pnl)
    fees = _amounts(state.metrics.fees)
    taxes = _amounts(state.metrics.taxes)
    has_asset_transfer = state.metrics.has_asset_transfer
    holding_events: list[HoldingPersistenceEvent] = []
    for root in roots:
        if not isinstance(root.event_type, InvestmentEventType) or not root.movements:
            raise _fail("Investment event type and movements are required.")
        holding_event = _holding_event(root)
        if not holding_event.movements:
            raise _fail("An investment event cannot contain only tax movements.")
        holding_events.append(holding_event)
        if root.realized_pnl is None:
            if root.realized_pnl_currency is not None:
                raise _fail("Realized P/L currency requires an amount.")
        else:
            pnl_currency = _currency(root.realized_pnl_currency)
            _add(realized_pnl, pnl_currency, _money(root.realized_pnl))
        if root.event_type is InvestmentEventType.asset_transfer:
            asset_movements = tuple(
                movement
                for movement in root.movements
                if movement.kind is InvestmentMovementKind.asset
            )
            if len(asset_movements) != 1:
                raise _fail("An asset transfer requires exactly one asset movement.")
            transfer = asset_movements[0]
            valuation = (
                transfer.price_per_unit,
                transfer.value_amount,
                transfer.value_currency,
            )
            if all(value is None for value in valuation):
                has_asset_transfer = True
            elif any(value is None for value in valuation):
                raise _fail("Asset transfer valuation must be complete or absent.")
            else:
                price_per_unit, value_amount, value_currency = valuation
                if (
                    not isinstance(price_per_unit, Decimal)
                    or not isinstance(value_amount, Decimal)
                    or not isinstance(value_currency, str)
                ):
                    raise _fail("Asset transfer valuation has invalid types.")
                amount = _money(canonical_rounded(value_amount, MONEY))
                if price_per_unit <= 0 or amount <= 0:
                    raise _fail("Asset transfer valuation must be positive.")
                _add(
                    net_deposits,
                    _currency(value_currency),
                    _signed(transfer.direction, amount),
                )
        for movement in root.movements:
            if movement.event_id != root.event_id or movement.account_id != root.account_id:
                raise _fail("Investment movement belongs to a different root.")
            if movement.kind is InvestmentMovementKind.asset:
                continue
            amount = _money(movement.quantity)
            currency = _currency(movement.currency)
            signed = _signed(movement.direction, amount)
            _add(cash, currency, signed)
            if movement.kind is InvestmentMovementKind.fee:
                if movement.direction is not MovementDirection.outgoing:
                    raise _fail("Fees must be outgoing.")
                _add(fees, currency, amount)
            if movement.kind is InvestmentMovementKind.tax:
                if movement.direction is not MovementDirection.outgoing:
                    raise _fail("Taxes must be outgoing.")
                _add(taxes, currency, amount)
            if (
                root.event_type
                in {
                    InvestmentEventType.cash_deposit,
                    InvestmentEventType.cash_withdrawal,
                }
                and movement.kind is InvestmentMovementKind.cash
            ):
                _add(net_deposits, currency, signed)
    try:
        projection = build_holding_delta_projection(
            account_id=state.account_id,
            baseline_holdings=state.holdings,
            events=tuple(holding_events),
        )
    except HoldingProjectionStateError as exc:
        raise _fail("Investment roots violate the canonical holding projection.") from exc
    return replace(
        state,
        cash_by_currency=_frozen_amounts(cash),
        holdings=projection.holdings,
        metrics=ReplayMetrics(
            net_deposits=_frozen_amounts(net_deposits),
            realized_pnl=_frozen_amounts(realized_pnl),
            fees=_frozen_amounts(fees),
            taxes=_frozen_amounts(taxes),
            has_asset_transfer=has_asset_transfer,
        ),
    )


def _apply_liability(state: AccountReplayState, root: LiabilityBalanceRoot) -> AccountReplayState:
    if state.account_type not in _LIABILITY_TYPES:
        raise _fail("Liability roots are valid only for liability accounts.")
    currency = _currency(root.currency)
    if currency != state.account_currency:
        raise _fail("Liability balance currency must equal the account currency.")
    principal = _money(root.outstanding_principal, nonnegative=True)
    interest = _money(root.accrued_interest, nonnegative=True)
    fees = _money(root.fees_outstanding, nonnegative=True)
    total = _add_money(_add_money(principal, interest), fees)
    return replace(
        state,
        liability=LiabilityReplayState(
            balance_id=root.balance_id,
            effective_at=root.effective_at,
            currency=currency,
            outstanding_principal=principal,
            accrued_interest=interest,
            fees_outstanding=fees,
            total_outstanding=total,
        ),
    )


def _timestamp_groups(roots: tuple[ReplayRoot, ...]) -> Iterable[tuple[ReplayRoot, ...]]:
    start = 0
    while start < len(roots):
        timestamp = root_timestamp(roots[start])
        end = start + 1
        while end < len(roots) and root_timestamp(roots[end]) == timestamp:
            end += 1
        yield roots[start:end]
        start = end


def advance_account_replay(
    state: AccountReplayState, roots: tuple[ReplayRoot, ...]
) -> AccountReplayState:
    """Apply complete timestamp groups and return a new immutable replay state."""

    if not isinstance(state, AccountReplayState):
        raise _fail("Replay state must be an account replay state.")
    _validate_account(state)
    supported = (TransactionRoot, InvestmentEventRoot, LiabilityBalanceRoot)
    if not isinstance(roots, tuple) or any(not isinstance(root, supported) for root in roots):
        raise _fail("Replay roots must be a tuple of canonical root models.")
    if any(not isinstance(root.eligible, bool) for root in roots):
        raise _fail("Replay root eligibility must be a boolean.")
    for root in roots:
        if root.eligible:
            _validate_root_common(state, root)
    ordered = canonical_roots(roots)
    if not ordered:
        return state
    for root in ordered:
        # Checkpoints are emitted only after a complete timestamp group. A new
        # root at the same timestamp would prove that checkpoint incomplete.
        if state.cursor is not None and root_timestamp(root) <= state.cursor.timestamp:
            raise _fail("Replay input overlaps its checkpoint cursor.")

    current = state
    for group in _timestamp_groups(ordered):
        # Work on a candidate. If any root fails, the immutable published input
        # and the previous complete group remain untouched to the caller.
        candidate = current
        investment_roots: list[InvestmentEventRoot] = []
        liability_roots = sum(isinstance(root, LiabilityBalanceRoot) for root in group)
        if liability_roots > 1:
            raise _fail("Multiple liability balances at one effective timestamp are ambiguous.")
        for root in group:
            if isinstance(root, TransactionRoot):
                candidate = _apply_transaction(candidate, root)
            elif isinstance(root, InvestmentEventRoot):
                investment_roots.append(root)
            elif isinstance(root, LiabilityBalanceRoot):
                candidate = _apply_liability(candidate, root)
        if investment_roots:
            candidate = _apply_investment(candidate, tuple(investment_roots))
        last = group[-1]
        current = replace(
            candidate,
            active=True,
            through=root_timestamp(last),
            cursor=ReplayCursor(
                timestamp=root_timestamp(last),
                kind=root_kind(last),
                entity_id=root_entity_id(last),
            ),
        )
    return current
