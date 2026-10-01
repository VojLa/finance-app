from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ClauseElement

from app.auth.models import AuthenticatedPrincipal
from app.db.models.canonical_lineage import UserReadModelPublicationModel
from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.db.models.investment_snapshots import PortfolioSnapshotModel
from app.db.models.snapshots import AccountSnapshotModel
from app.db.models.users import UserModel
from app.modules.portfolio_history.lattice import HistoryPublicRange
from app.modules.portfolio_snapshot.history_api_models import PortfolioHistoryPositionResponse
from app.modules.portfolio_snapshot.history_reader import (
    PublishedPortfolioSnapshotHistoryReader,
    _point_resolution_minutes,
    _snapshot_resolution_minutes,
    _unrealized_pnl_percentage,
)

_HistoryRows = tuple[
    tuple[
        PortfolioSnapshotModel | AccountSnapshotModel,
        AccountSnapshotModel | None,
        datetime,
    ],
    ...,
]


class _Rows:
    def __init__(self, values: tuple[tuple[object, ...], ...]) -> None:
        self.values = values

    def all(self) -> tuple[tuple[object, ...], ...]:
        return self.values


class _Scalars:
    def all(self) -> tuple[object, ...]:
        return ()


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: object) -> None:
        return None


class _Session:
    def __init__(
        self,
        *,
        publication_generation_id: str,
        portfolio_rows: tuple[tuple[object, ...], ...] = (),
        account_rows: tuple[tuple[object, ...], ...] = (),
        scope_rows: tuple[tuple[str, str | None], ...] = (("account-a", "account-a"),),
        membership_accepted: bool = True,
    ) -> None:
        self.publication_generation_id = publication_generation_id
        self.portfolio_rows = portfolio_rows
        self.account_rows = account_rows
        self.scope_rows = scope_rows
        self.membership_accepted = membership_accepted
        self.statements: list[object] = []

    def in_transaction(self) -> bool:
        return False

    async def rollback(self) -> None:
        return None

    def begin(self) -> _Transaction:
        return _Transaction()

    async def get(self, model: type[object], key: object) -> object | None:
        if model is UserReadModelPublicationModel:
            return SimpleNamespace(
                generation_id=self.publication_generation_id,
                version="publication-a",
                baseline_id="baseline-a",
            )
        if model is UserModel:
            return SimpleNamespace(base_currency="EUR")
        return SimpleNamespace()

    async def execute(self, statement: ClauseElement) -> _Rows:
        self.statements.append(statement)
        statement_sql = str(
            statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        )
        if '"PortfolioSnapshot"' in statement_sql:
            assert '"SnapshotSeriesPointLink"."validFromVersion"' in statement_sql
            assert '"NetWorthSnapshot"' not in statement_sql
            assert (
                '"PortfolioSnapshot".id = public."SnapshotSeriesPointLink"."portfolioSnapshotId"'
                in statement_sql
            )
            publication = await self.get(UserReadModelPublicationModel, "user-a")
            return _Rows(
                tuple(
                    (publication, 2, snapshot, valuation)
                    for snapshot, _linked_net_worth, valuation in self.portfolio_rows
                )
            )
        if (
            '"DailySnapshotBaselineAccount"' in statement_sql
            and '"AccountSnapshot"' not in statement_sql
        ):
            assert '"DailySnapshotBaselineAccount"."baselineId" = \'baseline-a\'' in statement_sql
            assert '"AccountMember"."acceptedAt" IS NOT NULL' in statement_sql
            return _Rows(self.scope_rows)
        assert '"SnapshotSeriesPointLink"."validFromVersion"' in statement_sql
        assert '"DailySnapshotBaselineAccount"."presentationSnapshotId"' in statement_sql
        publication = await self.get(UserReadModelPublicationModel, "user-a")
        return _Rows(tuple((publication, 2, *row) for row in self.account_rows))

    async def scalar(self, statement: object) -> object | None:
        self.statements.append(statement)
        statement_sql = str(
            cast(ClauseElement, statement).compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        if 'FROM public."AccountMember"' in statement_sql:
            assert '"AccountMember"."acceptedAt" IS NOT NULL' in statement_sql
            return SimpleNamespace() if self.membership_accepted else None
        return SimpleNamespace()

    async def scalars(self, _statement: object) -> _Scalars:
        return _Scalars()


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-a",
        email="user-a@example.test",
        name="User A",
    )


def _snapshot(
    *,
    snapshot_id: str,
    generation_id: str,
    granularity: SnapshotGranularity,
    currency: str = "EUR",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=snapshot_id,
        generation_id=generation_id,
        timestamp=datetime(2026, 9, 1),
        valuation_timestamp=datetime(2026, 9, 1),
        calculated_at=datetime(2026, 9, 1),
        exchange_rates={"snapshotRates": [], "historicalRateIds": []},
        granularity=granularity,
        currency=currency,
        cash_value=Decimal("100"),
        investment_value=Decimal("250"),
        investment_cost_basis=Decimal("210"),
        net_deposits_value=Decimal("200"),
        realized_pnl_value=Decimal("10"),
        unrealized_pnl_value=Decimal("40"),
        cash_value_by_currency={"EUR": "100"},
        investment_value_by_currency={"EUR": "250"},
        net_deposits_by_currency={"EUR": "200"},
    )


@pytest.mark.asyncio
async def test_portfolio_read_uses_head_links_across_physical_generations() -> None:
    published_a = _snapshot(
        snapshot_id="portfolio-a",
        generation_id="generation-a",
        granularity=SnapshotGranularity.day,
    )
    # A later physical generation can contribute a point to the same logical series.
    published_b = _snapshot(
        snapshot_id="portfolio-b",
        generation_id="generation-b",
        granularity=SnapshotGranularity.day,
    )
    published_b.timestamp = datetime(2026, 9, 2)
    session = _Session(
        publication_generation_id="generation-b",
        portfolio_rows=(
            (published_b, None, datetime(2026, 9, 2)),
            (published_a, None, datetime(2026, 9, 1)),
        ),
    )

    response = await PublishedPortfolioSnapshotHistoryReader(cast(AsyncSession, session)).read(
        principal=_principal(),
        history_range=HistoryPublicRange.all,
        account_id=None,
    )

    assert response.generation_id == "generation-b"
    assert [point.portfolio_snapshot_id for point in response.points] == [
        "portfolio-a",
        "portfolio-b",
    ]
    assert response.publication_version == 2


@pytest.mark.asyncio
async def test_portfolio_read_never_mixes_complete_net_worth_into_investment_scope() -> None:
    portfolio = _snapshot(
        snapshot_id="portfolio-a",
        generation_id="generation-a",
        granularity=SnapshotGranularity.day,
    )
    complete_net_worth = SimpleNamespace(
        total_net_worth=Decimal("999"),
        liabilities_value=Decimal("25"),
        liabilities_value_by_currency={"EUR": "25"},
    )
    session = _Session(
        publication_generation_id="generation-a",
        portfolio_rows=((portfolio, complete_net_worth, datetime(2026, 9, 1)),),
    )

    response = await PublishedPortfolioSnapshotHistoryReader(cast(AsyncSession, session)).read(
        principal=_principal(),
        history_range=HistoryPublicRange.all,
        account_id=None,
    )

    point = response.points[0]
    assert point.cash_value == Decimal("100")
    assert point.investment_value == Decimal("250")
    assert point.investment_cost_basis == Decimal("210")
    assert point.net_worth_value == Decimal("350")
    assert point.liabilities_value == Decimal("0")
    assert point.liabilities_by_currency == ()


@pytest.mark.asyncio
async def test_portfolio_read_fails_closed_when_published_scope_membership_was_revoked() -> None:
    published = _snapshot(
        snapshot_id="portfolio-a",
        generation_id="generation-a",
        granularity=SnapshotGranularity.day,
    )
    session = _Session(
        publication_generation_id="generation-a",
        portfolio_rows=((published, None, datetime(2026, 9, 1)),),
        scope_rows=(("account-a", None),),
    )

    response = await PublishedPortfolioSnapshotHistoryReader(cast(AsyncSession, session)).read(
        principal=_principal(),
        history_range=HistoryPublicRange.all,
        account_id=None,
    )

    assert response.state.value == "empty"
    assert response.points == ()


@pytest.mark.asyncio
async def test_portfolio_read_fails_closed_for_pending_membership() -> None:
    published = _snapshot(
        snapshot_id="portfolio-a",
        generation_id="generation-a",
        granularity=SnapshotGranularity.day,
    )
    session = _Session(
        publication_generation_id="generation-a",
        portfolio_rows=((published, None, datetime(2026, 9, 1)),),
        scope_rows=(("account-a", None),),
    )

    response = await PublishedPortfolioSnapshotHistoryReader(cast(AsyncSession, session)).read(
        principal=_principal(),
        history_range=HistoryPublicRange.all,
        account_id=None,
    )

    assert response.state.value == "empty"
    assert response.points == ()


@pytest.mark.asyncio
async def test_account_read_fails_closed_for_pending_membership() -> None:
    account_snapshot = _snapshot(
        snapshot_id="account-snapshot-a",
        generation_id="generation-a",
        granularity=SnapshotGranularity.minute,
    )
    session = _Session(
        publication_generation_id="generation-a",
        account_rows=((account_snapshot, datetime(2026, 9, 1)),),
        membership_accepted=False,
    )

    response = await PublishedPortfolioSnapshotHistoryReader(cast(AsyncSession, session)).read(
        principal=_principal(),
        history_range=HistoryPublicRange.all,
        account_id="account-a",
    )

    assert response.state.value == "empty"
    assert response.points == ()


@pytest.mark.asyncio
async def test_account_read_uses_account_snapshot_totals_and_pointer_generation() -> None:
    account_snapshot = _snapshot(
        snapshot_id="account-snapshot-a",
        generation_id="generation-a",
        granularity=SnapshotGranularity.minute,
        currency="USD",
    )
    account_snapshot.cash_value = Decimal("110")
    account_snapshot.investment_value = Decimal("260")
    account_snapshot.liabilities_value = Decimal("25")
    account_snapshot.total_value = Decimal("345")
    account_snapshot.liabilities_value_by_currency = {"USD": "20", "EUR": "5"}
    account_snapshot.cash_value_by_currency = {"USD": "80", "EUR": "30"}
    account_snapshot.investment_value_by_currency = {"USD": "200", "EUR": "60"}
    account_snapshot.exchange_rates = {
        "snapshotRates": [{"timestamp": "2026-08-31T23:59:00.000"}],
        "historicalRateIds": ["event-date-rate-does-not-control-freshness"],
    }
    session = _Session(
        publication_generation_id="generation-a",
        account_rows=((account_snapshot, datetime(2026, 9, 1, 0, 0, 5)),),
    )

    response = await PublishedPortfolioSnapshotHistoryReader(cast(AsyncSession, session)).read(
        principal=_principal(),
        history_range=HistoryPublicRange.all,
        account_id="account-a",
    )

    point = response.points[0]
    assert point.resolution_minutes == 1
    assert point.liabilities_value == Decimal("25")
    assert point.net_worth_value == Decimal("345")
    assert response.currency == "USD"
    assert point.cash_by_currency is not None
    assert {(item.currency, item.value) for item in point.cash_by_currency} == {
        ("EUR", Decimal("30")),
        ("USD", Decimal("80")),
    }
    assert response.resolutions == (1,)
    assert response.preferred_resolution_minutes == 1
    assert response.valuation_timestamp == datetime(2026, 8, 31, 23, 59)


@pytest.mark.asyncio
async def test_native_currency_breakdown_serializes_without_losing_fractional_digits() -> None:
    snapshot = _snapshot(
        snapshot_id="account-precise",
        generation_id="generation-a",
        granularity=SnapshotGranularity.minute,
    )
    snapshot.cash_value_by_currency = {"EUR": "0.123456789123"}
    snapshot.liabilities_value = Decimal(0)
    snapshot.total_value = Decimal("350")
    snapshot.liabilities_value_by_currency = {}
    session = _Session(
        publication_generation_id="generation-a",
        account_rows=((snapshot, datetime(2026, 9, 1)),),
    )

    response = await PublishedPortfolioSnapshotHistoryReader(cast(AsyncSession, session)).read(
        principal=_principal(), history_range=HistoryPublicRange.all, account_id="account-a"
    )

    assert response.model_dump(mode="json", by_alias=True)["points"][0]["cashByCurrency"] == [
        {"currency": "EUR", "value": "0.123456789123"}
    ]


@pytest.mark.parametrize(
    ("granularity", "expected_minutes"),
    (
        (SnapshotGranularity.minute, 1),
        (SnapshotGranularity.hour, 60),
        (SnapshotGranularity.day, 1_440),
        (SnapshotGranularity.week, 10_080),
    ),
)
def test_resolution_metadata_comes_from_snapshot_granularity(
    granularity: SnapshotGranularity,
    expected_minutes: int,
) -> None:
    assert (
        _snapshot_resolution_minutes(SimpleNamespace(granularity=granularity)) == expected_minutes
    )


@pytest.mark.parametrize(
    ("value", "cost_basis", "expected"),
    (
        (Decimal("150"), Decimal("100"), Decimal("50.0000")),
        (Decimal("75"), Decimal("100"), Decimal("-25.0000")),
        (Decimal("100"), Decimal("100"), Decimal("0.0000")),
        (Decimal("10"), Decimal("0"), None),
        (Decimal("10"), None, None),
    ),
)
def test_position_unrealized_percentage_uses_exact_snapshot_money(
    value: Decimal,
    cost_basis: Decimal | None,
    expected: Decimal | None,
) -> None:
    assert _unrealized_pnl_percentage(value=value, cost_basis=cost_basis) == expected


def test_position_unrealized_percentage_serializes_as_exact_signed_decimal() -> None:
    payload = PortfolioHistoryPositionResponse(
        listing_id="listing-a",
        symbol="ASSET",
        quantity=Decimal("1.2500000000"),
        value=Decimal("75"),
        cost_basis=Decimal("100"),
        allocation_pct=Decimal("56.6500"),
        unrealized_pnl_pct=Decimal("-25.0000"),
    ).model_dump(mode="json", by_alias=True, exclude_none=True)

    assert payload["unrealizedPnlPct"] == "-25.0000"


def test_all_range_sampling_keeps_oldest_and_newest_snapshot() -> None:
    start = datetime(2020, 1, 1)
    chronological = cast(
        _HistoryRows,
        tuple(
            (SimpleNamespace(timestamp=start + timedelta(days=index)), None, start)
            for index in range(600)
        ),
    )

    selected = PublishedPortfolioSnapshotHistoryReader._select_rows(tuple(reversed(chronological)))

    assert len(selected) == 480
    assert selected[0][0].timestamp == chronological[0][0].timestamp
    assert selected[-1][0].timestamp == chronological[-1][0].timestamp
    assert all(left[0].timestamp < right[0].timestamp for left, right in pairwise(selected))


def test_rebuild_series_reports_actual_spacing_instead_of_storage_granularity() -> None:
    start = datetime(2026, 1, 1)
    rows = cast(
        _HistoryRows,
        tuple(
            (
                SimpleNamespace(
                    timestamp=start + timedelta(minutes=30 * index),
                    granularity=SnapshotGranularity.minute,
                    source=SnapshotSource.holdings_recalculation,
                ),
                None,
                start,
            )
            for index in range(3)
        ),
    )

    assert [_point_resolution_minutes(rows, index) for index in range(3)] == [30, 30, 30]


@pytest.mark.asyncio
async def test_mixed_resolution_coverage_follows_chronological_point_runs() -> None:
    start = datetime(2026, 9, 1)
    snapshots = []
    for index, (offset, granularity) in enumerate(
        (
            (0, SnapshotGranularity.minute),
            (1, SnapshotGranularity.minute),
            (61, SnapshotGranularity.hour),
            (91, SnapshotGranularity.minute),
        )
    ):
        snapshot = _snapshot(
            snapshot_id=f"portfolio-{index}",
            generation_id="generation-a",
            granularity=granularity,
        )
        snapshot.timestamp = start + timedelta(minutes=offset)
        snapshots.append(snapshot)
    session = _Session(
        publication_generation_id="generation-a",
        portfolio_rows=tuple((snapshot, None, start) for snapshot in reversed(snapshots)),
    )

    response = await PublishedPortfolioSnapshotHistoryReader(cast(AsyncSession, session)).read(
        principal=_principal(), history_range=HistoryPublicRange.all, account_id=None
    )

    assert [point.resolution_minutes for point in response.points] == [1, 1, 60, 30]
    assert response.resolutions == (1, 30, 60)
    assert [
        (segment.resolution_minutes, segment.start, segment.end) for segment in response.coverage
    ] == [
        (1, start, start + timedelta(minutes=61)),
        (60, start + timedelta(minutes=61), start + timedelta(minutes=91)),
        (30, start + timedelta(minutes=91), start + timedelta(minutes=91, milliseconds=1)),
    ]


def test_downsampled_day_resolution_reports_selected_spacing() -> None:
    start = datetime(2020, 1, 1)
    rows = cast(
        _HistoryRows,
        tuple(
            (
                SimpleNamespace(
                    timestamp=start + timedelta(days=2 * index),
                    granularity=SnapshotGranularity.day,
                ),
                None,
                start,
            )
            for index in range(480)
        ),
    )

    assert all(_point_resolution_minutes(rows, index) == 2_880 for index in range(len(rows)))
