from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import uuid5

import pytest

from app.db.models.canonical_lineage import SnapshotGenerationModel, SnapshotGenerationTargetModel
from app.db.models.enums import AccountType, SnapshotGranularity, SnapshotSource
from app.db.models.investment_snapshots import (
    InvestmentAccountSnapshotItemModel,
    InvestmentAccountSnapshotModel,
    PortfolioSnapshotItemAccountModel,
    PortfolioSnapshotItemModel,
    PortfolioSnapshotModel,
)
from app.modules.net_worth.evidence_service import SelectedAccountSnapshotIdentity
from app.modules.portfolio_snapshot.writer import (
    _INVESTMENT_NAMESPACE,
    _PORTFOLIO_NAMESPACE,
    PortfolioSnapshotWriteError,
    PortfolioSnapshotWriter,
    WritePortfolioSnapshotCommand,
    _allocations,
    _breakdown_sum,
    _position_evidence,
    valuation_evidence_timestamp,
)


def test_valuation_freshness_uses_oldest_price_or_current_fx_only() -> None:
    calculated_at = datetime(2026, 9, 3, 12)
    evidence = {
        "version": 1,
        "snapshotRates": [
            {"timestamp": "2026-09-03T11:20:00.000"},
            {"timestamp": "2026-09-03T11:05:00.000"},
        ],
        "historicalRates": [{"timestamp": "2020-01-01T00:00:00.000"}],
        "historicalRateIds": ["event-date-rate"],
    }

    assert valuation_evidence_timestamp(
        (datetime(2026, 9, 3, 11, 30), datetime(2026, 9, 3, 11, 10)),
        evidence,
        calculated_at,
    ) == datetime(2026, 9, 3, 11, 5)
    assert valuation_evidence_timestamp((), evidence, calculated_at) == datetime(2026, 9, 3, 11, 5)
    assert (
        valuation_evidence_timestamp(
            (), {"snapshotRates": [], "historicalRateIds": ["old"]}, calculated_at
        )
        == calculated_at
    )


def test_breakdown_sum_preserves_all_native_currencies() -> None:
    result = _breakdown_sum(
        (
            {"CZK": "100.125", "EUR": Decimal("2.50")},
            {"CZK": "-0.125", "USD": 3},
        )
    )

    assert result == {"CZK": "100.000", "EUR": "2.50", "USD": "3"}


@pytest.mark.parametrize(
    "breakdown",
    (
        {"usd": "1"},
        {"USD": "not-a-decimal"},
        {"EUR": "NaN"},
    ),
)
def test_breakdown_sum_fails_closed_for_malformed_currency_evidence(
    breakdown: dict[str, object],
) -> None:
    with pytest.raises(PortfolioSnapshotWriteError):
        _breakdown_sum((breakdown,))


def test_allocation_rounding_is_exact_and_deterministic() -> None:
    allocations = _allocations((Decimal("1"), Decimal("1"), Decimal("1")))

    assert allocations == (Decimal("33.3334"), Decimal("33.3333"), Decimal("33.3333"))
    assert sum(allocations, Decimal(0)) == Decimal("100.0000")


def test_projection_ids_are_deterministic_and_generation_salted() -> None:
    investment_name = "generation-a\0account-snapshot-a"
    portfolio_name = "\0".join(("generation-a", "user-a", "2026-09-03T12:00:00.000", "CZK", "day"))

    assert uuid5(_INVESTMENT_NAMESPACE, investment_name) == uuid5(
        _INVESTMENT_NAMESPACE, investment_name
    )
    assert uuid5(_INVESTMENT_NAMESPACE, investment_name) != uuid5(
        _INVESTMENT_NAMESPACE, "generation-b\0account-snapshot-a"
    )
    assert uuid5(_PORTFOLIO_NAMESPACE, portfolio_name) != uuid5(
        _PORTFOLIO_NAMESPACE,
        portfolio_name.replace("generation-a", "generation-b", 1),
    )


def test_write_command_is_immutable() -> None:
    command = WritePortfolioSnapshotCommand(
        user_id="user-a",
        generation_id="generation-a",
        timestamp=datetime(2026, 9, 3, 12, 0),
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        currency="CZK",
        calculation_version=1,
        calculated_at=datetime(2026, 9, 3, 12, 0),
        created_at=datetime(2026, 9, 3, 12, 0),
        required_account_snapshot_identities=(),
    )

    with pytest.raises(FrozenInstanceError):
        command.user_id = "user-b"  # type: ignore[misc]


def _position(**changes: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "asset_id": "asset-a",
        "symbol": "AAA",
        "price_per_unit": Decimal("10"),
        "price_currency": "USD",
        "price_source": "source-a",
        "price_timestamp": datetime(2026, 9, 3, 12, 0),
    }
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    "changes",
    (
        {"price_per_unit": Decimal("11")},
        {"price_currency": "EUR"},
        {"price_source": "source-b"},
        {"price_timestamp": datetime(2026, 9, 3, 12, 1)},
    ),
)
def test_position_evidence_rejects_conflicting_listing_contributions(
    changes: dict[str, object],
) -> None:
    with pytest.raises(PortfolioSnapshotWriteError):
        _position_evidence(
            cast(
                tuple[InvestmentAccountSnapshotItemModel, ...],
                (_position(), _position(**changes)),
            )
        )


class _ScalarResult:
    def __init__(self, values: tuple[object, ...]) -> None:
        self._values = values

    def all(self) -> tuple[object, ...]:
        return self._values


class _Transaction:
    async def __aenter__(self) -> "_Transaction":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class _ExactRetrySession:
    def __init__(
        self, *, existing: SimpleNamespace, scalar_results: tuple[tuple[object, ...], ...]
    ) -> None:
        self._existing = existing
        self._scalar_results = iter(scalar_results)
        self.added: list[object] = []

    def in_transaction(self) -> bool:
        return False

    def begin(self) -> _Transaction:
        return _Transaction()

    async def execute(self, statement: object) -> None:
        return None

    async def get(self, model: type[object], key: object, **kwargs: object) -> object:
        if model is SnapshotGenerationModel:
            return SimpleNamespace(state="staged", published_at=None)
        if model is SnapshotGenerationTargetModel:
            return SimpleNamespace()
        if model is PortfolioSnapshotModel:
            return self._existing
        raise AssertionError(f"unexpected model lookup: {model}")

    async def scalars(self, statement: object) -> _ScalarResult:
        return _ScalarResult(next(self._scalar_results))

    def add(self, row: object) -> None:
        self.added.append(row)

    def add_all(self, rows: object) -> None:
        self.added.extend(rows)  # type: ignore[arg-type]


class _CreateSession(_ExactRetrySession):
    def __init__(self, scalar_results: tuple[tuple[object, ...], ...]) -> None:
        super().__init__(existing=None, scalar_results=scalar_results)  # type: ignore[arg-type]
        self.flushes: list[tuple[type[object], ...]] = []

    async def flush(self) -> None:
        self.flushes.append(tuple(type(row) for row in self.added))


def _retry_command() -> WritePortfolioSnapshotCommand:
    now = datetime(2026, 9, 3, 12, 0)
    return WritePortfolioSnapshotCommand(
        user_id="user-a",
        generation_id="generation-a",
        timestamp=now,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        currency="CZK",
        calculation_version=1,
        calculated_at=now,
        created_at=now,
        required_account_snapshot_identities=(
            SelectedAccountSnapshotIdentity(account_id="account-a", snapshot_id="snapshot-a"),
        ),
    )


def _retry_scalar_results(command: WritePortfolioSnapshotCommand) -> tuple[tuple[object, ...], ...]:
    source = SimpleNamespace(
        id="snapshot-a",
        account_id="account-a",
        generation_id=command.generation_id,
        timestamp=command.timestamp,
        granularity=command.granularity,
        source=command.source,
        currency=command.currency,
        cash_value=Decimal("1"),
        investment_value=Decimal("10"),
        investment_cost_basis=Decimal("8"),
        net_deposits_value=Decimal("8"),
        realized_pnl_value=Decimal("0"),
        unrealized_pnl_value=Decimal("2"),
        fees_value=Decimal("0"),
        taxes_value=Decimal("0"),
        cash_value_by_currency={"CZK": "1"},
        investment_value_by_currency={"USD": "10"},
        investment_cost_basis_by_currency={"USD": "8"},
        net_deposits_by_currency={"USD": "8"},
        realized_pnl_by_currency={"USD": "0"},
        unrealized_pnl_by_currency={"USD": "2"},
        fees_by_currency={"USD": "0"},
        taxes_by_currency={"USD": "0"},
        exchange_rates={"USD": "22"},
        calculated_at=command.calculated_at,
        calculation_version=command.calculation_version,
    )
    item = SimpleNamespace(
        id="account-item-a",
        asset_id="asset-a",
        listing_id="listing-a",
        symbol="AAA",
        quantity=Decimal("1"),
        price_per_unit=Decimal("10"),
        price_currency="USD",
        price_source="source-a",
        price_timestamp=command.calculated_at,
        value=Decimal("10"),
        cost_basis=Decimal("8"),
        allocation_pct=Decimal("100"),
        native_value=Decimal("10"),
        value_currency="USD",
        native_cost_basis=Decimal("8"),
        native_cost_currency="USD",
    )
    return ((source,), (SimpleNamespace(id="account-a", type=AccountType.broker),), (item,))


@pytest.mark.asyncio
async def test_exact_retry_returns_existing_projection_without_duplicate_rows() -> None:
    command = _retry_command()
    portfolio_id = str(
        uuid5(
            _PORTFOLIO_NAMESPACE,
            "\0".join(
                (
                    command.generation_id,
                    command.user_id,
                    command.timestamp.isoformat(timespec="milliseconds"),
                    command.currency,
                    command.granularity.value,
                )
            ),
        )
    )
    existing = SimpleNamespace(
        id=portfolio_id,
        user_id=command.user_id,
        generation_id=command.generation_id,
        timestamp=command.timestamp,
        granularity=command.granularity,
        source=command.source,
        currency=command.currency,
        valuation_timestamp=command.calculated_at,
        calculated_at=command.calculated_at,
        calculation_version=command.calculation_version,
    )
    first_session = _ExactRetrySession(
        existing=existing,
        scalar_results=_retry_scalar_results(command),
    )
    second_session = _ExactRetrySession(
        existing=existing,
        scalar_results=_retry_scalar_results(command),
    )

    first_result = await PortfolioSnapshotWriter(first_session).write(command)  # type: ignore[arg-type]
    second_result = await PortfolioSnapshotWriter(second_session).write(command)  # type: ignore[arg-type]

    assert first_result == second_result
    assert first_result.portfolio_snapshot_id == portfolio_id
    assert first_result.investment_account_snapshot_ids
    assert first_session.added == []
    assert second_session.added == []


@pytest.mark.asyncio
async def test_create_flushes_every_composite_fk_parent_before_its_children() -> None:
    command = _retry_command()
    session = _CreateSession(_retry_scalar_results(command))

    result = await PortfolioSnapshotWriter(session).write(command)  # type: ignore[arg-type]

    assert result.position_count == 1
    assert len(session.flushes) == 4
    first, second, third, fourth = session.flushes
    assert InvestmentAccountSnapshotModel in first
    assert InvestmentAccountSnapshotItemModel not in first
    assert InvestmentAccountSnapshotItemModel in second
    assert PortfolioSnapshotModel in second
    assert PortfolioSnapshotItemModel in third
    assert PortfolioSnapshotItemAccountModel not in third
    assert PortfolioSnapshotItemAccountModel in fourth


@pytest.mark.asyncio
async def test_persisted_investment_and_portfolio_freshness_uses_oldest_required_evidence() -> None:
    base = _retry_command()
    command = replace(
        base,
        required_account_snapshot_identities=(
            SelectedAccountSnapshotIdentity(account_id="account-a", snapshot_id="snapshot-a"),
            SelectedAccountSnapshotIdentity(account_id="account-b", snapshot_id="snapshot-b"),
        ),
    )
    original, account, first_item = (values[0] for values in _retry_scalar_results(command))
    source_a = SimpleNamespace(**vars(original))
    source_a.exchange_rates = {
        "snapshotRates": [{"timestamp": "2026-09-03T11:00:00.000"}],
        "historicalRateIds": ["very-old-event-rate"],
    }
    item_a = SimpleNamespace(**vars(first_item))
    item_a.price_timestamp = datetime(2026, 9, 3, 11, 30)
    source_b = SimpleNamespace(**vars(original))
    source_b.id = "snapshot-b"
    source_b.account_id = "account-b"
    source_b.exchange_rates = {
        "snapshotRates": [{"timestamp": "2026-09-03T10:00:00.000"}],
        "historicalRateIds": ["2020-rate"],
    }
    item_b = SimpleNamespace(**vars(first_item))
    item_b.id = "item-b"
    item_b.listing_id = "listing-b"
    item_b.asset_id = "asset-b"
    item_b.symbol = "BBB"
    item_b.price_timestamp = datetime(2026, 9, 3, 10, 30)
    session = _CreateSession(
        (
            (source_a, source_b),
            (account, SimpleNamespace(id="account-b", type=AccountType.broker)),
            (item_a,),
            (item_b,),
        )
    )

    await PortfolioSnapshotWriter(session).write(command)  # type: ignore[arg-type]

    investments = tuple(
        row for row in session.added if isinstance(row, InvestmentAccountSnapshotModel)
    )
    portfolio = next(row for row in session.added if isinstance(row, PortfolioSnapshotModel))
    assert {row.account_id: row.valuation_timestamp for row in investments} == {
        "account-a": datetime(2026, 9, 3, 11),
        "account-b": datetime(2026, 9, 3, 10),
    }
    assert portfolio.valuation_timestamp == datetime(2026, 9, 3, 10)
