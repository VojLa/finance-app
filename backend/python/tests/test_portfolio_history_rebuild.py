from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.db.models.enums import (
    AccountType,
    AssetType,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    SnapshotSeriesJobKind,
    TransactionClassification,
    TransactionType,
)
from app.modules.holdings.persistence_projection import (
    HoldingPersistenceEvent,
    HoldingPersistenceMovement,
    build_holding_delta_projection,
)
from app.modules.jobs.lifecycle import LeaseIdentity
from app.modules.market_data.source_policy import CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY
from app.modules.portfolio_history.builder import executor as history_executor_module
from app.modules.portfolio_history.builder.executor import (
    RebuildPortfolioHistoryJobExecutor,
    _advance_rebuild_schedule,
    _generation_id,
    _superseded_job_error,
)
from app.modules.portfolio_history.builder.planning import build_rebuild_generation_plan
from app.modules.portfolio_history.jobs.repository import ClaimedPortfolioHistoryJob
from app.modules.portfolio_history.jobs.worker import PermanentPortfolioHistoryJobError
from app.modules.portfolio_history_rebuild import (
    MAX_CHECKPOINT_BYTES,
    CurrencyAmount,
    InvestmentEventRoot,
    LiabilityBalanceRoot,
    PortfolioHistoryReplayError,
    ReplayMetrics,
    ReplayRootKind,
    TransactionRoot,
    advance_account_replay,
    decode_replay_checkpoint,
    empty_account_replay_state,
    encode_replay_checkpoint,
)
from app.modules.snapshot_refresh.series_executor import generation_id_for_job

T0 = datetime(2024, 1, 2, 10, 0)
T1 = datetime(2024, 2, 3, 11, 30)


def test_superseded_capture_has_terminal_actionable_code() -> None:
    error = _superseded_job_error("capture")

    assert isinstance(error, PermanentPortfolioHistoryJobError)
    assert error.code == "history_capture_superseded"
    assert "newer publication" in error.message


@pytest.mark.asyncio
async def test_crash_after_switch_finalizes_without_loading_scope_or_provider() -> None:
    started_at = datetime(2026, 9, 28, 12)
    capture_at = started_at + timedelta(minutes=30)
    job = SimpleNamespace(
        id="capture-job",
        user_id="user-1",
        kind=SnapshotSeriesJobKind.capture,
        payload={"capture_at": capture_at},
        checkpoint={},
        started_at=started_at,
        created_at=started_at,
    )
    generation_id = _generation_id(cause="capture", job_id=job.id, started_at=started_at)
    physical_generation = generation_id_for_job(f"{job.id}:{generation_id}")
    persistence = SimpleNamespace(
        has_receipt=AsyncMock(return_value=True),
        finalize=AsyncMock(),
    )
    scope_loader = AsyncMock(side_effect=AssertionError("scope must not load"))
    provider = SimpleNamespace(acquire=AsyncMock(side_effect=AssertionError("provider called")))
    series = SimpleNamespace(execute=AsyncMock(side_effect=AssertionError("series called")))
    checkpoint = AsyncMock(side_effect=AssertionError("checkpoint called"))
    executor = RebuildPortfolioHistoryJobExecutor(
        cast(Any, None),
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        market_acquirer=cast(Any, provider),
        calculation_version=1,
        persistence=cast(Any, persistence),
        scope_loader=cast(Any, scope_loader),
        snapshot_series_executor=cast(Any, series),
        clock=lambda: started_at,
    )
    lease = LeaseIdentity(job.id, "worker", 2)

    result = await executor.execute(
        ClaimedPortfolioHistoryJob(cast(Any, job), lease), checkpoint=checkpoint
    )

    assert result.outcome == "completed"
    persistence.has_receipt.assert_awaited_once_with(
        user_id="user-1", job_id=job.id, generation_id=physical_generation
    )
    persistence.finalize.assert_awaited_once_with(
        user_id="user-1",
        job_id=job.id,
        lease=lease,
        generation_id=physical_generation,
        dirty_epoch=None,
        capture_at=capture_at,
        rebuild_covered_through=None,
        now=started_at,
    )
    scope_loader.assert_not_awaited()
    provider.acquire.assert_not_awaited()
    series.execute.assert_not_awaited()
    checkpoint.assert_not_awaited()


def test_rebuild_completion_advances_stale_scheduler_cursor_to_current_bucket() -> None:
    schedule = SimpleNamespace(
        last_captured_bucket=datetime(2026, 9, 4, 20),
        next_capture_at=datetime(2026, 9, 4, 20, 30),
        updated_at=datetime(2026, 9, 4, 20),
    )
    now = datetime(2026, 9, 29, 6, 21)

    _advance_rebuild_schedule(
        cast(Any, schedule),
        covered_through=datetime(2026, 9, 29, 5, 26),
        now=now,
    )

    assert schedule.last_captured_bucket == datetime(2026, 9, 29, 5)
    assert schedule.next_capture_at == datetime(2026, 9, 29, 5, 30)
    assert schedule.updated_at == now


def test_rebuild_completion_never_moves_newer_scheduler_cursor_backwards() -> None:
    schedule = SimpleNamespace(
        last_captured_bucket=datetime(2026, 9, 29, 6),
        next_capture_at=datetime(2026, 9, 29, 6, 30),
        updated_at=datetime(2026, 9, 29, 6),
    )

    _advance_rebuild_schedule(
        cast(Any, schedule),
        covered_through=datetime(2026, 9, 29, 5, 26),
        now=datetime(2026, 9, 29, 6, 21),
    )

    assert schedule.last_captured_bucket == datetime(2026, 9, 29, 6)
    assert schedule.next_capture_at == datetime(2026, 9, 29, 6, 30)
    assert schedule.updated_at == datetime(2026, 9, 29, 6)


@pytest.mark.asyncio
async def test_rebuild_executor_replays_only_suffix_and_checkpoint(monkeypatch: Any) -> None:
    through = datetime(2026, 9, 28, 12)
    first = through - timedelta(days=2)
    dirty_from = through - timedelta(hours=1)
    expected = build_rebuild_generation_plan(
        first_event_at=first, dirty_from=dirty_from, covered_through=through
    )
    replayed: list[datetime] = []

    def replay(_scope: object, *, timestamps: tuple[datetime, ...]) -> dict[datetime, object]:
        replayed.extend(timestamps)
        return {timestamp: object() for timestamp in timestamps}

    monkeypatch.setattr(history_executor_module, "replay_accounts_at", replay)
    provider_failure = RuntimeError("provider unavailable")
    provider = SimpleNamespace(acquire=AsyncMock(side_effect=provider_failure))
    persistence = SimpleNamespace(has_receipt=AsyncMock(return_value=False))
    job = SimpleNamespace(
        id="rebuild-job",
        user_id="user-1",
        kind=SnapshotSeriesJobKind.rebuild,
        payload={"dirty_epoch": 1, "dirty_from": dirty_from},
        checkpoint={},
        started_at=through,
        created_at=through,
    )
    executor = RebuildPortfolioHistoryJobExecutor(
        cast(Any, None),
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        market_acquirer=cast(Any, provider),
        calculation_version=1,
        persistence=cast(Any, persistence),
        scope_loader=cast(Any, AsyncMock(return_value=SimpleNamespace(earliest_event_at=first))),
        snapshot_series_executor=cast(Any, SimpleNamespace(execute=AsyncMock())),
        clock=lambda: through,
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await executor.execute(
            ClaimedPortfolioHistoryJob(cast(Any, job), LeaseIdentity(job.id, "worker", 1)),
            checkpoint=AsyncMock(),
        )

    series_replay = {
        history_executor_module._ceil_snapshot_minute(item.representative_at)
        for item in expected.suffix_buckets
    }
    assert set(replayed) == set(expected.replay_timestamps) | series_replay
    prefix_only = (
        {item.representative_at for item in expected.prefix_buckets}
        - {item.representative_at for item in expected.suffix_buckets}
        - {through}
    )
    assert prefix_only.isdisjoint(replayed)


def _state(account_type: AccountType, account_id: str = "account-1"):
    return empty_account_replay_state(
        account_id=account_id, account_type=account_type, account_currency="CZK"
    )


def _movement(
    event_id: str,
    suffix: str,
    *,
    kind: InvestmentMovementKind,
    direction: MovementDirection,
    quantity: str,
    currency: str,
    asset: bool = False,
    price: str | None = None,
    value: str | None = None,
    value_currency: str | None = None,
) -> HoldingPersistenceMovement:
    return HoldingPersistenceMovement(
        movement_id=f"{event_id}-{suffix}",
        event_id=event_id,
        account_id="account-1",
        kind=kind,
        direction=direction,
        quantity=Decimal(quantity),
        currency=currency,
        asset_id="asset-aapl" if asset else None,
        listing_id="listing-aapl" if asset else None,
        listing_asset_id="asset-aapl" if asset else None,
        source_symbol="AAPL" if asset else None,
        source_asset_type=AssetType.stock if asset else None,
        price_per_unit=None if price is None else Decimal(price),
        value_amount=None if value is None else Decimal(value),
        value_currency=value_currency,
        listing_currency="USD" if asset else None,
    )


def _trading_event(
    event_id: str,
    timestamp: datetime,
    *,
    direction: MovementDirection,
    quantity: str,
    price: str,
    value: str,
    fee: str,
    realized_pnl: str | None = None,
) -> InvestmentEventRoot:
    cash_direction = (
        MovementDirection.outgoing
        if direction is MovementDirection.incoming
        else MovementDirection.incoming
    )
    return InvestmentEventRoot(
        event_id=event_id,
        account_id="account-1",
        event_type=InvestmentEventType.trade,
        event_date=timestamp,
        realized_pnl=None if realized_pnl is None else Decimal(realized_pnl),
        realized_pnl_currency=None if realized_pnl is None else "USD",
        movements=(
            _movement(
                event_id,
                "asset",
                kind=InvestmentMovementKind.asset,
                direction=direction,
                quantity=quantity,
                currency="AAPL",
                asset=True,
                price=price,
                value=value,
                value_currency="USD",
            ),
            _movement(
                event_id,
                "cash",
                kind=InvestmentMovementKind.cash,
                direction=cash_direction,
                quantity=value,
                currency="USD",
                value=value,
                value_currency="USD",
            ),
            _movement(
                event_id,
                "fee",
                kind=InvestmentMovementKind.fee,
                direction=MovementDirection.outgoing,
                quantity=fee,
                currency="USD",
                value=fee,
                value_currency="USD",
            ),
        ),
    )


def _transaction(
    transaction_id: str,
    timestamp: datetime,
    amount: str,
    *,
    account_id: str = "account-1",
    eligible: bool = True,
) -> TransactionRoot:
    value = Decimal(amount)
    return TransactionRoot(
        transaction_id=transaction_id,
        account_id=account_id,
        timestamp=timestamp,
        amount=value,
        currency="CZK",
        transaction_type=(
            TransactionType.transfer
            if transaction_id.startswith("transfer")
            else TransactionType.income
            if value > 0
            else TransactionType.expense
        ),
        classification=(
            TransactionClassification.internal_transfer
            if transaction_id.startswith("transfer")
            else TransactionClassification.real_income
            if value > 0
            else TransactionClassification.real_expense
        ),
        eligible=eligible,
    )


def _investment_transaction(
    transaction_id: str,
    timestamp: datetime,
    amount: str,
) -> TransactionRoot:
    return TransactionRoot(
        transaction_id=transaction_id,
        account_id="account-1",
        timestamp=timestamp,
        amount=Decimal(amount),
        currency="USD",
        transaction_type=TransactionType.transfer,
        classification=TransactionClassification.investment_transfer,
        eligible=True,
    )


def _investment_operational_transaction(
    transaction_id: str,
    timestamp: datetime,
    amount: str,
) -> TransactionRoot:
    value = Decimal(amount)
    return TransactionRoot(
        transaction_id=transaction_id,
        account_id="account-1",
        timestamp=timestamp,
        amount=value,
        currency="USD",
        transaction_type=TransactionType.income if value > 0 else TransactionType.expense,
        classification=(
            TransactionClassification.real_income
            if value > 0
            else TransactionClassification.real_expense
        ),
        eligible=True,
    )


def test_trading212_buy_sell_fee_reuses_canonical_holding_cost_basis() -> None:
    buy = _trading_event(
        "buy",
        T0,
        direction=MovementDirection.incoming,
        quantity="2.0000000000",
        price="100.0000000000",
        value="200.000000",
        fee="2.000000",
    )
    sell = _trading_event(
        "sell",
        T1,
        direction=MovementDirection.outgoing,
        quantity="1.0000000000",
        price="120.0000000000",
        value="120.000000",
        fee="1.000000",
        realized_pnl="20.000000",
    )

    result = advance_account_replay(_state(AccountType.broker), (sell, buy))

    assert result.active is True
    assert [(item.currency, item.amount) for item in result.cash_by_currency] == [
        ("USD", Decimal("-83.000000"))
    ]
    assert len(result.holdings) == 1
    holding = result.holdings[0]
    assert holding.quantity == Decimal("1.0000000000")
    assert holding.avg_buy_price == Decimal("100.0000000000")
    assert holding.cost_basis_by_currency == (("USD", Decimal("100.0000000000")),)
    assert result.metrics.fees[0].amount == Decimal("3.000000")
    assert result.metrics.realized_pnl[0].amount == Decimal("20.000000")


def test_operational_transactions_change_broker_cash_and_net_deposits_only() -> None:
    buy = _trading_event(
        "buy",
        T0,
        direction=MovementDirection.incoming,
        quantity="1.0000000000",
        price="100.0000000000",
        value="100.000000",
        fee="2.000000",
    )
    debit = _investment_operational_transaction("card-debit", T1, "-12.000000")
    cashback = _investment_operational_transaction("cashback", T1, "4.000000")

    result = advance_account_replay(_state(AccountType.broker), (buy, debit, cashback))

    assert [(item.currency, item.amount) for item in result.cash_by_currency] == [
        ("USD", Decimal("-110.000000"))
    ]
    assert [(item.currency, item.amount) for item in result.metrics.net_deposits] == [
        ("USD", Decimal("-8.000000"))
    ]
    assert [(item.currency, item.amount) for item in result.metrics.fees] == [
        ("USD", Decimal("2.000000"))
    ]
    assert result.metrics.realized_pnl == ()
    assert result.metrics.taxes == ()


def test_misclassified_broker_transactions_remain_rejected() -> None:
    invalid = replace(
        _transaction("expense", T0, "-1.000000"),
        classification=TransactionClassification.real_income,
    )
    with pytest.raises(PortfolioHistoryReplayError, match="supported cash-flow"):
        advance_account_replay(
            _state(AccountType.broker),
            (invalid,),
        )


@pytest.mark.parametrize("account_type", [AccountType.exchange, AccountType.crypto_wallet])
def test_anycoin_incoming_asset_transfer_preserves_unknown_basis(
    account_type: AccountType,
) -> None:
    movement = _movement(
        "anycoin",
        "asset",
        kind=InvestmentMovementKind.asset,
        direction=MovementDirection.incoming,
        quantity="0.0200000000",
        currency="BTC",
        asset=True,
    )
    movement = replace(
        movement,
        asset_id="asset-btc",
        listing_id="listing-btc",
        listing_asset_id="asset-btc",
        source_symbol="BTC",
        source_asset_type=AssetType.crypto,
        listing_currency="EUR",
    )
    event = InvestmentEventRoot(
        event_id="anycoin",
        account_id="account-1",
        event_type=InvestmentEventType.asset_transfer,
        event_date=T0,
        movements=(movement,),
    )

    result = advance_account_replay(_state(account_type), (event,))

    assert result.holdings[0].quantity == Decimal("0.0200000000")
    assert result.holdings[0].avg_buy_price is None
    assert result.holdings[0].cost_basis_by_currency is None
    assert result.metrics.has_asset_transfer is True


@pytest.mark.parametrize(
    ("direction", "expected_flow"),
    [
        (MovementDirection.incoming, Decimal("25000.000000")),
        (MovementDirection.outgoing, Decimal("0.000000")),
    ],
)
def test_valued_anycoin_transfer_updates_basis_and_external_flow(
    direction: MovementDirection,
    expected_flow: Decimal,
) -> None:
    movement = replace(
        _movement(
            "valued-anycoin",
            "asset",
            kind=InvestmentMovementKind.asset,
            direction=direction,
            quantity="0.0200000000",
            currency="BTC",
            asset=True,
        ),
        asset_id="asset-btc",
        listing_id="listing-btc",
        listing_asset_id="asset-btc",
        source_symbol="BTC",
        source_asset_type=AssetType.crypto,
        listing_currency="CZK",
        price_per_unit=Decimal("1250000.0000000000"),
        value_amount=Decimal("25000.0000000000"),
        value_currency="CZK",
    )
    event = InvestmentEventRoot(
        event_id="valued-anycoin",
        account_id="account-1",
        event_type=InvestmentEventType.asset_transfer,
        event_date=T0,
        movements=(movement,),
    )
    baseline = _state(AccountType.exchange)
    if direction is MovementDirection.outgoing:
        incoming = replace(
            event,
            event_id="valued-anycoin-in",
            event_date=T0,
            movements=(
                replace(
                    movement,
                    movement_id="valued-anycoin-in:asset",
                    event_id="valued-anycoin-in",
                    direction=MovementDirection.incoming,
                ),
            ),
        )
        baseline = advance_account_replay(baseline, (incoming,))
        event = replace(event, event_date=T1)

    result = advance_account_replay(baseline, (event,))

    if expected_flow:
        assert result.metrics.net_deposits[-1].amount == expected_flow
    else:
        assert result.metrics.net_deposits == ()
    assert result.metrics.has_asset_transfer is False
    if direction is MovementDirection.incoming:
        assert result.holdings[0].avg_buy_price == Decimal("1250000.0000000000")
        assert result.holdings[0].cost_basis_by_currency is not None
        assert result.holdings[0].cost_basis_by_currency[0] == (
            "CZK",
            Decimal("25000.0000000000"),
        )
    else:
        assert result.holdings == ()


def test_partial_outbound_anycoin_transfer_reduces_basis_without_realized_pnl() -> None:
    incoming_movement = replace(
        _movement(
            "anycoin-in",
            "asset",
            kind=InvestmentMovementKind.asset,
            direction=MovementDirection.incoming,
            quantity="0.0200000000",
            currency="BTC",
            asset=True,
        ),
        asset_id="asset-btc",
        listing_id="listing-btc",
        listing_asset_id="asset-btc",
        source_symbol="BTC",
        source_asset_type=AssetType.crypto,
        listing_currency="CZK",
        price_per_unit=Decimal("1250000.0000000000"),
        value_amount=Decimal("25000.0000000000"),
        value_currency="CZK",
    )
    outgoing_movement = replace(
        incoming_movement,
        movement_id="anycoin-out:asset",
        event_id="anycoin-out",
        direction=MovementDirection.outgoing,
        quantity=Decimal("0.0050000000"),
        value_amount=Decimal("6250.0000000000"),
    )
    result = advance_account_replay(
        _state(AccountType.exchange),
        (
            InvestmentEventRoot(
                event_id="anycoin-in",
                account_id="account-1",
                event_type=InvestmentEventType.asset_transfer,
                event_date=T0,
                movements=(incoming_movement,),
            ),
            InvestmentEventRoot(
                event_id="anycoin-out",
                account_id="account-1",
                event_type=InvestmentEventType.asset_transfer,
                event_date=T1,
                movements=(outgoing_movement,),
            ),
        ),
    )

    assert result.holdings[0].quantity == Decimal("0.0150000000")
    assert result.holdings[0].cost_basis_by_currency == (("CZK", Decimal("18750.0000000000")),)
    assert result.metrics.net_deposits == (
        CurrencyAmount(currency="CZK", amount=Decimal("18750.000000")),
    )
    assert result.metrics.realized_pnl == ()


@pytest.mark.parametrize("account_type", [AccountType.bank, AccountType.cash, AccountType.savings])
def test_rb_cash_accounts_apply_signed_transactions_and_transfers(
    account_type: AccountType,
) -> None:
    result = advance_account_replay(
        _state(account_type),
        (
            _transaction("expense", T1, "-25.500000"),
            _transaction("income", T0, "100.000000"),
            _transaction("transfer-out", T1, "-10.000000"),
        ),
    )
    assert result.cash_by_currency[0].amount == Decimal("64.500000")


def test_rb_transfer_is_account_local_and_eur_is_not_converted() -> None:
    czk = advance_account_replay(
        _state(AccountType.bank, "czk"),
        (_transaction("transfer-out", T0, "-250.000000", account_id="czk"),),
    )
    eur_root = replace(
        _transaction("transfer-in", T0, "10.000000", account_id="eur"), currency="EUR"
    )
    eur = advance_account_replay(_state(AccountType.savings, "eur"), (eur_root,))
    assert czk.cash_by_currency[0].amount == Decimal("-250.000000")
    assert eur.cash_by_currency[0].currency == "EUR"
    assert eur.cash_by_currency[0].amount == Decimal("10.000000")


@pytest.mark.parametrize("account_type", [AccountType.loan, AccountType.mortgage])
def test_liability_balance_is_explicit_latest_replacement(account_type: AccountType) -> None:
    first = LiabilityBalanceRoot(
        "balance-a",
        "account-1",
        T0,
        "CZK",
        Decimal("100.000000"),
        Decimal("2.000000"),
        Decimal("3.000000"),
    )
    latest = LiabilityBalanceRoot(
        "balance-b",
        "account-1",
        T1,
        "CZK",
        Decimal("80.000000"),
        Decimal("1.000000"),
        Decimal("0.500000"),
    )
    result = advance_account_replay(_state(account_type), (latest, first))
    assert result.liability is not None
    assert result.liability.balance_id == "balance-b"
    assert result.liability.total_outstanding == Decimal("81.500000")


def test_credit_card_replays_signed_transactions_as_cash() -> None:
    result = advance_account_replay(
        _state(AccountType.credit_card),
        (_transaction("purchase", T0, "-2500.000000"),),
    )

    assert result.liability is None
    assert result.cash_by_currency[0].amount == Decimal("-2500.000000")


def test_liability_currency_and_same_time_ambiguity_fail_closed() -> None:
    state = _state(AccountType.loan)
    foreign = LiabilityBalanceRoot(
        "foreign",
        "account-1",
        T0,
        "EUR",
        Decimal("1.000000"),
        Decimal("0.000000"),
        Decimal("0.000000"),
    )
    with pytest.raises(PortfolioHistoryReplayError, match="account currency"):
        advance_account_replay(state, (foreign,))
    first = replace(foreign, balance_id="a", currency="CZK")
    second = replace(first, balance_id="b")
    with pytest.raises(PortfolioHistoryReplayError, match="ambiguous"):
        advance_account_replay(state, (first, second))


def test_ineligible_roots_do_not_activate_or_advance_account() -> None:
    state = _state(AccountType.bank)
    result = advance_account_replay(
        state, (_transaction("archived", T0, "1.000000", eligible=False),)
    )
    assert result is state
    assert result.active is False
    assert result.through is None


def test_order_is_deterministic_duplicates_fail_and_checkpoint_cursor_cannot_overlap() -> None:
    first = _transaction("a", T0, "1.000000")
    second = _transaction("b", T0, "2.000000")
    forward = advance_account_replay(_state(AccountType.bank), (first, second))
    reverse = advance_account_replay(_state(AccountType.bank), (second, first))
    assert forward == reverse
    assert forward.cursor is not None and forward.cursor.entity_id == "b"
    with pytest.raises(PortfolioHistoryReplayError, match="Duplicate"):
        advance_account_replay(_state(AccountType.bank), (first, first))
    with pytest.raises(PortfolioHistoryReplayError, match="overlaps"):
        advance_account_replay(forward, (_transaction("c", T0, "1.000000"),))


def test_checkpoint_has_canonical_fixed_scale_hash_roundtrip_and_rejects_corruption() -> None:
    state = advance_account_replay(
        _state(AccountType.bank), (_transaction("income", T0, "12.340000"),)
    )
    document = encode_replay_checkpoint(state)
    assert encode_replay_checkpoint(state) == document
    assert hashlib.sha256(document.payload).hexdigest() == document.sha256
    assert len(document.payload) < MAX_CHECKPOINT_BYTES
    assert b'"12.340000"' in document.payload
    assert decode_replay_checkpoint(document.payload, document.sha256) == state

    corrupted = document.payload.replace(b"12.340000", b"12.350000")
    with pytest.raises(PortfolioHistoryReplayError, match="hash mismatch"):
        decode_replay_checkpoint(corrupted, document.sha256)

    noncanonical = document.payload.replace(
        b'{"schemaVersion":1,"state":', b'{ "schemaVersion":1,"state":'
    )
    noncanonical_hash = hashlib.sha256(noncanonical).hexdigest()
    with pytest.raises(PortfolioHistoryReplayError, match="not canonical"):
        decode_replay_checkpoint(noncanonical, noncanonical_hash)

    duplicate = document.payload.replace(
        b'{"schemaVersion":1,', b'{"schemaVersion":1,"schemaVersion":1,', 1
    )
    duplicate_hash = hashlib.sha256(duplicate).hexdigest()
    with pytest.raises(PortfolioHistoryReplayError, match="duplicate keys"):
        decode_replay_checkpoint(duplicate, duplicate_hash)


def test_checkpoint_rejects_wrong_scale_and_oversize() -> None:
    state = advance_account_replay(
        _state(AccountType.bank), (_transaction("income", T0, "12.340000"),)
    )
    document = encode_replay_checkpoint(state)
    wrong_scale = document.payload.replace(b"12.340000", b"12.34")
    with pytest.raises(PortfolioHistoryReplayError, match="fixed-scale"):
        decode_replay_checkpoint(wrong_scale, hashlib.sha256(wrong_scale).hexdigest())
    oversized = b" " * (MAX_CHECKPOINT_BYTES + 1)
    with pytest.raises(PortfolioHistoryReplayError, match="too large"):
        decode_replay_checkpoint(oversized, hashlib.sha256(oversized).hexdigest())
    huge_state = empty_account_replay_state(
        account_id="a" * MAX_CHECKPOINT_BYTES,
        account_type=AccountType.bank,
        account_currency="CZK",
    )
    with pytest.raises(PortfolioHistoryReplayError, match="exceeds"):
        encode_replay_checkpoint(huge_state)
    deeply_nested = (b"[" * 2_000) + b"0" + (b"]" * 2_000)
    with pytest.raises(PortfolioHistoryReplayError):
        decode_replay_checkpoint(
            deeply_nested,
            hashlib.sha256(deeply_nested).hexdigest(),
        )


def test_wrong_root_domain_fails_closed_without_mutating_input() -> None:
    state = _state(AccountType.bank)
    liability = LiabilityBalanceRoot(
        "balance",
        "account-1",
        T0,
        "CZK",
        Decimal("1.000000"),
        Decimal("0.000000"),
        Decimal("0.000000"),
    )
    with pytest.raises(PortfolioHistoryReplayError, match="liability accounts"):
        advance_account_replay(state, (liability,))
    assert state.active is False


def test_asset_quantity_uses_quantity_not_money_scale_and_unknown_root_fails_cleanly() -> None:
    event = _trading_event(
        "fractional",
        T0,
        direction=MovementDirection.incoming,
        quantity="6.6328245400",
        price="1.0000000000",
        value="6.632825",
        fee="0.000001",
    )
    result = advance_account_replay(_state(AccountType.broker), (event,))
    assert result.holdings[0].quantity == Decimal("6.6328245400")
    with pytest.raises(PortfolioHistoryReplayError, match="canonical root models"):
        advance_account_replay(_state(AccountType.bank), (object(),))  # type: ignore[arg-type]


def test_runtime_types_and_timestamps_fail_with_replay_errors() -> None:
    state = _state(AccountType.bank)
    invalid_state = replace(state, account_type="bank")
    with pytest.raises(PortfolioHistoryReplayError, match="account type"):
        advance_account_replay(invalid_state, ())
    with pytest.raises(PortfolioHistoryReplayError, match="active flag"):
        advance_account_replay(replace(state, active=1), ())

    root = _transaction("income", T0, "1.000000")
    invalid_roots = (
        replace(root, transaction_type="income"),  # type: ignore[arg-type]
        replace(root, classification="real_income"),  # type: ignore[arg-type]
        replace(root, eligible=1),  # type: ignore[arg-type]
        replace(root, timestamp=T0.replace(tzinfo=UTC)),
    )
    for invalid_root in invalid_roots:
        with pytest.raises(PortfolioHistoryReplayError):
            advance_account_replay(state, (invalid_root,))

    investment = _trading_event(
        "typed",
        T0,
        direction=MovementDirection.incoming,
        quantity="1.0000000000",
        price="1.0000000000",
        value="1.000000",
        fee="0.000001",
    )
    movement = replace(investment.movements[0], kind="asset")  # type: ignore[arg-type]
    with pytest.raises(PortfolioHistoryReplayError, match="kind or direction"):
        advance_account_replay(
            _state(AccountType.broker),
            (replace(investment, movements=(movement, *investment.movements[1:])),),
        )

    active = advance_account_replay(state, (root,))
    assert active.cursor is not None
    with pytest.raises(PortfolioHistoryReplayError, match="cursor kind"):
        encode_replay_checkpoint(
            replace(
                active,
                cursor=replace(active.cursor, kind=ReplayRootKind.investment_event),
            )
        )


@pytest.mark.parametrize(
    ("transaction_type", "classification"),
    [
        (TransactionType.income, TransactionClassification.real_expense),
        (TransactionType.expense, TransactionClassification.real_income),
        (TransactionType.transfer, TransactionClassification.needs_review),
    ],
)
def test_transaction_type_and_classification_must_be_consistent(
    transaction_type: TransactionType,
    classification: TransactionClassification,
) -> None:
    root = replace(
        _transaction("income", T0, "1.000000"),
        amount=(
            Decimal("-1.000000")
            if transaction_type is TransactionType.expense
            else Decimal("1.000000")
        ),
        transaction_type=transaction_type,
        classification=classification,
    )
    with pytest.raises(PortfolioHistoryReplayError, match="classification"):
        advance_account_replay(_state(AccountType.bank), (root,))


def test_checkpoint_encoder_rejects_noncanonical_currency_maps() -> None:
    state = advance_account_replay(
        _state(AccountType.bank), (_transaction("income", T0, "1.000000"),)
    )
    invalid_maps = (
        (
            CurrencyAmount("EUR", Decimal("1.000000")),
            CurrencyAmount("CZK", Decimal("1.000000")),
        ),
        (
            CurrencyAmount("CZK", Decimal("1.000000")),
            CurrencyAmount("CZK", Decimal("2.000000")),
        ),
        (CurrencyAmount("CZK", Decimal("0.000000")),),
    )
    for invalid_map in invalid_maps:
        with pytest.raises(PortfolioHistoryReplayError):
            encode_replay_checkpoint(replace(state, cash_by_currency=invalid_map))

    duplicate = encode_replay_checkpoint(state).payload.replace(
        b'"cashByCurrency":[',
        b'"cashByCurrency":[{"amount":"1.000000","currency":"CZK"},',
    )
    with pytest.raises(PortfolioHistoryReplayError, match="duplicate currencies"):
        decode_replay_checkpoint(duplicate, hashlib.sha256(duplicate).hexdigest())


def test_checkpoint_rejects_malformed_holdings_and_account_listing_identity() -> None:
    movement = _movement(
        "holding",
        "asset",
        kind=InvestmentMovementKind.asset,
        direction=MovementDirection.incoming,
        quantity="0.0200000000",
        currency="BTC",
        asset=True,
    )
    movement = replace(
        movement,
        asset_id="asset-btc",
        listing_id="listing-btc",
        listing_asset_id="asset-btc",
        source_symbol="BTC",
        source_asset_type=AssetType.crypto,
        listing_currency="EUR",
    )
    root = InvestmentEventRoot(
        event_id="holding",
        account_id="account-1",
        event_type=InvestmentEventType.asset_transfer,
        event_date=T0,
        movements=(movement,),
    )
    state = advance_account_replay(_state(AccountType.exchange), (root,))
    holding = state.holdings[0]
    malformed = (
        replace(holding, account_id="other-account"),
        replace(holding, listing_id=""),
        replace(holding, quantity=Decimal("0.0000000000")),
        replace(holding, quantity=Decimal("-0.0200000000")),
        replace(holding, avg_buy_price=Decimal("1.0000000000")),
        replace(
            holding,
            cost_basis_by_currency=(("EUR", Decimal("1.0000000000")),),
        ),
        replace(holding, current_value=Decimal("1.0000000000")),
    )
    for invalid_holding in malformed:
        with pytest.raises(PortfolioHistoryReplayError, match="holdings"):
            encode_replay_checkpoint(replace(state, holdings=(invalid_holding,)))
    with pytest.raises(PortfolioHistoryReplayError, match="holdings"):
        encode_replay_checkpoint(replace(state, holdings=(holding, holding)))

    document = encode_replay_checkpoint(state)
    zero_quantity = document.payload.replace(
        b'"quantity":"0.0200000000"', b'"quantity":"0.0000000000"'
    )
    with pytest.raises(PortfolioHistoryReplayError, match="holdings"):
        decode_replay_checkpoint(
            zero_quantity,
            hashlib.sha256(zero_quantity).hexdigest(),
        )


@pytest.mark.parametrize(
    ("quantity", "listing_asset_id"),
    [
        ("0.0000000000", "asset-btc"),
        ("-0.0200000000", "asset-btc"),
        ("0.0200000000", "different-asset"),
    ],
)
def test_asset_roots_reject_nonpositive_quantity_and_listing_identity(
    quantity: str, listing_asset_id: str
) -> None:
    movement = _movement(
        "invalid-asset",
        "asset",
        kind=InvestmentMovementKind.asset,
        direction=MovementDirection.incoming,
        quantity=quantity,
        currency="BTC",
        asset=True,
    )
    movement = replace(
        movement,
        asset_id="asset-btc",
        listing_id="listing-btc",
        listing_asset_id=listing_asset_id,
        source_symbol="BTC",
        source_asset_type=AssetType.crypto,
        listing_currency="EUR",
    )
    root = InvestmentEventRoot(
        event_id="invalid-asset",
        account_id="account-1",
        event_type=InvestmentEventType.asset_transfer,
        event_date=T0,
        movements=(movement,),
    )
    with pytest.raises(PortfolioHistoryReplayError):
        advance_account_replay(_state(AccountType.exchange), (root,))


def test_liability_checkpoint_revalidates_identity_currency_and_total() -> None:
    root = LiabilityBalanceRoot(
        "balance",
        "account-1",
        T0,
        "CZK",
        Decimal("10.000000"),
        Decimal("2.000000"),
        Decimal("1.000000"),
    )
    state = advance_account_replay(_state(AccountType.loan), (root,))
    assert state.liability is not None
    invalid_liabilities = (
        replace(state.liability, balance_id=""),
        replace(state.liability, currency="EUR"),
        replace(state.liability, total_outstanding=Decimal("12.000000")),
        replace(state.liability, outstanding_principal=Decimal("-1.000000")),
    )
    for liability in invalid_liabilities:
        with pytest.raises(PortfolioHistoryReplayError):
            encode_replay_checkpoint(replace(state, liability=liability))


def test_same_timestamp_event_order_matches_current_holding_projection() -> None:
    buy = _trading_event(
        "a-buy",
        T0,
        direction=MovementDirection.incoming,
        quantity="2.0000000000",
        price="100.0000000000",
        value="200.000000",
        fee="2.000000",
    )
    sell = _trading_event(
        "b-sell",
        T0,
        direction=MovementDirection.outgoing,
        quantity="1.0000000000",
        price="120.0000000000",
        value="120.000000",
        fee="1.000000",
    )
    replayed = advance_account_replay(_state(AccountType.broker), (sell, buy))
    persistence_events = tuple(
        HoldingPersistenceEvent(
            event_id=root.event_id,
            account_id=root.account_id,
            event_type=root.event_type,
            event_date=root.event_date,
            external_id=root.external_id,
            movements=root.movements,
        )
        for root in (sell, buy)
    )
    expected = build_holding_delta_projection(
        account_id="account-1",
        baseline_holdings=(),
        events=persistence_events,
    )
    assert replayed.holdings == expected.holdings
    assert replayed.cursor is not None and replayed.cursor.entity_id == "b-sell"


def test_tax_movement_is_positive_outgoing_canonical_cash_evidence() -> None:
    trade = _trading_event(
        "taxed",
        T0,
        direction=MovementDirection.incoming,
        quantity="1.0000000000",
        price="100.0000000000",
        value="100.000000",
        fee="2.000000",
    )
    tax = _movement(
        "taxed",
        "tax",
        kind=InvestmentMovementKind.tax,
        direction=MovementDirection.outgoing,
        quantity="1.000000",
        currency="USD",
        value="1.000000",
        value_currency="USD",
    )
    result = advance_account_replay(
        _state(AccountType.broker),
        (replace(trade, movements=(*trade.movements, tax)),),
    )
    assert result.cash_by_currency[0].amount == Decimal("-103.000000")
    assert result.metrics.taxes == (CurrencyAmount("USD", Decimal("1.000000")),)

    negative_tax = replace(
        tax,
        quantity=Decimal("-1.000000"),
        value_amount=Decimal("-1.000000"),
    )
    with pytest.raises(PortfolioHistoryReplayError, match="Tax movement"):
        advance_account_replay(
            _state(AccountType.broker),
            (replace(trade, movements=(*trade.movements, negative_tax)),),
        )


def test_account_type_state_domains_are_enforced_in_checkpoint() -> None:
    cursor_state = advance_account_replay(
        _state(AccountType.bank), (_transaction("income", T0, "1.000000"),)
    )
    with pytest.raises(PortfolioHistoryReplayError, match="Cash-like"):
        encode_replay_checkpoint(
            replace(
                cursor_state,
                metrics=ReplayMetrics(
                    fees=(CurrencyAmount("CZK", Decimal("1.000000")),),
                ),
            )
        )
    with pytest.raises(PortfolioHistoryReplayError, match="requires a balance"):
        encode_replay_checkpoint(
            replace(cursor_state, account_type=AccountType.loan, cash_by_currency=())
        )
