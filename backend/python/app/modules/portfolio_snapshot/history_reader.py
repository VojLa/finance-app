"""Fast portfolio chart reader over immutable published snapshot rows."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.accounts import AccountMemberModel
from app.db.models.canonical_lineage import (
    DailySnapshotBaselineAccountModel,
    UserReadModelPublicationModel,
)
from app.db.models.enums import SnapshotGranularity
from app.db.models.investment_snapshots import (
    PortfolioSnapshotItemAccountModel,
    PortfolioSnapshotItemModel,
    PortfolioSnapshotModel,
)
from app.db.models.snapshot_series_publication import (
    SnapshotSeriesHeadModel,
    SnapshotSeriesPointLinkModel,
)
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
)
from app.db.models.users import UserModel
from app.modules.portfolio_snapshot.history_api_models import (
    GenerationPortfolioHistoryPointResponse,
    PortfolioHistoryCoverageResponse,
    PortfolioHistoryCurrencyAmountResponse,
    PortfolioHistoryPositionAccountResponse,
    PortfolioHistoryPositionResponse,
    PortfolioHistoryResponse,
)
from app.modules.portfolio_snapshot.history_contracts import (
    HistoryPublicRange,
    PortfolioHistoryReadState,
)
from app.modules.portfolio_snapshot.history_contracts import (
    PortfolioSnapshotHistoryUnavailableError as GenerationPortfolioHistoryUnavailableError,
)
from app.modules.portfolio_snapshot.writer import valuation_evidence_timestamp

_MAX_POINTS = 480
_STALE_AFTER = timedelta(minutes=30)
_RANGE_AGE = {
    HistoryPublicRange.one_day: timedelta(days=1),
    HistoryPublicRange.one_week: timedelta(days=7),
    HistoryPublicRange.one_month: timedelta(days=31),
    HistoryPublicRange.three_months: timedelta(days=93),
    HistoryPublicRange.six_months: timedelta(days=186),
    HistoryPublicRange.one_year: timedelta(days=366),
    HistoryPublicRange.five_years: timedelta(days=366 * 5),
    HistoryPublicRange.ten_years: timedelta(days=366 * 10),
}
_SNAPSHOT_RESOLUTION_MINUTES: dict[object, int] = {
    SnapshotGranularity.minute: 1,
    SnapshotGranularity.hour: 60,
    SnapshotGranularity.day: 1_440,
    SnapshotGranularity.week: 10_080,
}
_PERCENTAGE_QUANTUM = Decimal("0.0001")

_SnapshotModel = PortfolioSnapshotModel | AccountSnapshotModel
_AggregateModel = AccountSnapshotModel | None
_HistoryRow = tuple[_SnapshotModel, _AggregateModel, datetime]
_HistoryRows = tuple[_HistoryRow, ...]


def _currency_amounts(value: object) -> tuple[PortfolioHistoryCurrencyAmountResponse, ...]:
    if value is None:
        return ()
    if not isinstance(value, Mapping):
        raise GenerationPortfolioHistoryUnavailableError()
    result: list[PortfolioHistoryCurrencyAmountResponse] = []
    try:
        for currency, amount in sorted(value.items()):
            if not isinstance(currency, str):
                raise ValueError
            result.append(
                PortfolioHistoryCurrencyAmountResponse(
                    currency=currency,
                    value=Decimal(str(amount)),
                )
            )
    except (InvalidOperation, ValueError, TypeError):
        raise GenerationPortfolioHistoryUnavailableError() from None
    return tuple(result)


def _snapshot_resolution_minutes(snapshot: object) -> int:
    granularity = getattr(snapshot, "granularity", None)
    try:
        return _SNAPSHOT_RESOLUTION_MINUTES[granularity]
    except (KeyError, TypeError):
        # A month is calendar-relative and cannot truthfully be represented by
        # this integer-minute API contract. Published baselines permit only
        # minute and day rows today; fail closed if that contract changes.
        raise GenerationPortfolioHistoryUnavailableError() from None


def _unrealized_pnl_percentage(*, value: Decimal, cost_basis: Decimal | None) -> Decimal | None:
    if cost_basis is None or cost_basis <= 0:
        return None
    return (((value - cost_basis) / cost_basis) * Decimal(100)).quantize(
        _PERCENTAGE_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def _point_resolution_minutes(rows: _HistoryRows, index: int) -> int:
    snapshot = rows[index][0]
    deltas: list[int] = []
    for neighbor in (index - 1, index + 1):
        if 0 <= neighbor < len(rows):
            seconds = abs((rows[neighbor][0].timestamp - snapshot.timestamp).total_seconds())
            if seconds <= 0 or seconds % 60:
                raise GenerationPortfolioHistoryUnavailableError()
            deltas.append(int(seconds // 60))
    return max(_snapshot_resolution_minutes(snapshot), min(deltas, default=0))


class PublishedPortfolioSnapshotHistoryReader:
    """Read only already-published rows; never replay or call a provider."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def read(
        self,
        *,
        principal: AuthenticatedPrincipal,
        history_range: HistoryPublicRange,
        account_id: str | None,
    ) -> PortfolioHistoryResponse:
        if self.session.in_transaction():
            await self.session.rollback()
        now = datetime.now(UTC).replace(tzinfo=None)
        cutoff = (
            None if history_range is HistoryPublicRange.all else now - _RANGE_AGE[history_range]
        )
        try:
            async with self.session.begin():
                rows: _HistoryRows
                user = await self.session.get(UserModel, principal.user_id)
                if user is None:
                    return self._empty(history_range, "CZK")
                currency = user.base_currency
                if account_id is None:
                    rows, publication, series_version = await self._portfolio_rows(
                        user_id=principal.user_id,
                        cutoff=cutoff,
                    )
                    if publication is None:
                        return self._empty(history_range, currency)
                    if not await self._published_scope_is_authorized(
                        user_id=principal.user_id,
                        baseline_id=publication.baseline_id,
                    ):
                        return self._empty(history_range, currency)
                else:
                    membership = await self.session.scalar(
                        select(AccountMemberModel).where(
                            AccountMemberModel.account_id == account_id,
                            AccountMemberModel.user_id == principal.user_id,
                            AccountMemberModel.accepted_at.is_not(None),
                        )
                    )
                    if membership is None:
                        return self._empty(history_range, currency)
                    rows, publication, series_version = await self._account_rows(
                        user_id=principal.user_id,
                        account_id=account_id,
                        cutoff=cutoff,
                    )
                    if publication is None:
                        return self._empty(history_range, currency)
                ordered = self._select_rows(rows)
                positions = await self._positions(
                    rows=ordered,
                    account_id=account_id,
                )
        except SQLAlchemyError:
            if self.session.in_transaction():
                await self.session.rollback()
            raise GenerationPortfolioHistoryUnavailableError() from None

        if not ordered:
            return self._empty(history_range, currency)
        points: list[GenerationPortfolioHistoryPointResponse] = []
        for index, row in enumerate(ordered):
            snapshot, aggregate, _published_at = row
            resolution_minutes = _point_resolution_minutes(ordered, index)
            if account_id is None:
                liabilities_value = Decimal(0)
                net_worth_value = snapshot.cash_value + snapshot.investment_value
                liabilities_breakdown = None
            else:
                account_aggregate = aggregate
                liabilities_value = (
                    account_aggregate.liabilities_value
                    if account_aggregate is not None
                    else Decimal(0)
                )
                net_worth_value = (
                    account_aggregate.total_value
                    if account_aggregate is not None
                    else snapshot.cash_value + snapshot.investment_value
                )
                liabilities_breakdown = (
                    account_aggregate.liabilities_value_by_currency
                    if account_aggregate is not None
                    else None
                )
            points.append(
                GenerationPortfolioHistoryPointResponse(
                    timestamp=snapshot.timestamp,
                    resolution_minutes=resolution_minutes,
                    cash_value=snapshot.cash_value,
                    investment_value=snapshot.investment_value,
                    investment_cost_basis=snapshot.investment_cost_basis,
                    liabilities_value=liabilities_value,
                    net_worth_value=net_worth_value,
                    net_invested_value=snapshot.net_deposits_value,
                    portfolio_snapshot_id=snapshot.id,
                    realized_pnl_value=snapshot.realized_pnl_value,
                    unrealized_pnl_value=snapshot.unrealized_pnl_value,
                    cash_by_currency=_currency_amounts(snapshot.cash_value_by_currency),
                    investment_by_currency=_currency_amounts(snapshot.investment_value_by_currency),
                    liabilities_by_currency=_currency_amounts(liabilities_breakdown),
                    net_invested_by_currency=_currency_amounts(snapshot.net_deposits_by_currency),
                    positions=positions.get(snapshot.id, ()),
                )
            )
        latest_snapshot = ordered[-1][0]
        latest_valuation_timestamp = ordered[-1][2]
        latest_resolution_minutes = _point_resolution_minutes(ordered, len(ordered) - 1)
        resolutions = tuple(sorted({point.resolution_minutes for point in points}))
        coverage: list[PortfolioHistoryCoverageResponse] = []
        for index, point in enumerate(points):
            if index > 0 and points[index - 1].resolution_minutes == point.resolution_minutes:
                continue
            next_change = next(
                (
                    later.timestamp
                    for later in points[index + 1 :]
                    if later.resolution_minutes != point.resolution_minutes
                ),
                points[-1].timestamp + timedelta(milliseconds=1),
            )
            coverage.append(
                PortfolioHistoryCoverageResponse(
                    resolution_minutes=point.resolution_minutes,
                    start=point.timestamp,
                    end=next_change,
                )
            )
        return PortfolioHistoryResponse(
            range=history_range,
            state=PortfolioHistoryReadState.ready,
            currency=latest_snapshot.currency,
            generation_id=publication.generation_id,
            publication_version=series_version,
            covered_through=latest_snapshot.timestamp,
            preferred_resolution_minutes=latest_resolution_minutes,
            resolutions=resolutions,
            coverage=tuple(coverage),
            points=tuple(points),
            publication_id=publication.version,
            valuation_timestamp=latest_valuation_timestamp,
            is_stale=now - latest_valuation_timestamp > _STALE_AFTER,
        )

    async def _published_scope_is_authorized(self, *, user_id: str, baseline_id: str) -> bool:
        rows = tuple(
            (
                await self.session.execute(
                    select(
                        DailySnapshotBaselineAccountModel.account_id,
                        AccountMemberModel.account_id,
                    )
                    .outerjoin(
                        AccountMemberModel,
                        (
                            AccountMemberModel.account_id
                            == DailySnapshotBaselineAccountModel.account_id
                        )
                        & (AccountMemberModel.user_id == user_id)
                        & (AccountMemberModel.accepted_at.is_not(None)),
                    )
                    .where(DailySnapshotBaselineAccountModel.baseline_id == baseline_id)
                )
            ).all()
        )
        return bool(rows) and all(member_account_id is not None for _, member_account_id in rows)

    async def _portfolio_rows(
        self,
        *,
        user_id: str,
        cutoff: datetime | None,
    ) -> tuple[
        tuple[tuple[PortfolioSnapshotModel, None, datetime], ...],
        UserReadModelPublicationModel | None,
        int,
    ]:
        visible = (
            (SnapshotSeriesPointLinkModel.user_id == UserReadModelPublicationModel.user_id)
            & (SnapshotSeriesPointLinkModel.valid_from_version <= SnapshotSeriesHeadModel.version)
            & (
                SnapshotSeriesPointLinkModel.valid_to_version.is_(None)
                | (SnapshotSeriesPointLinkModel.valid_to_version > SnapshotSeriesHeadModel.version)
            )
        )
        if cutoff is not None:
            visible &= SnapshotSeriesPointLinkModel.timestamp >= cutoff
        statement = (
            select(
                UserReadModelPublicationModel,
                SnapshotSeriesHeadModel.version,
                PortfolioSnapshotModel,
                PortfolioSnapshotModel.valuation_timestamp,
            )
            .join(
                SnapshotSeriesHeadModel,
                SnapshotSeriesHeadModel.id == UserReadModelPublicationModel.series_head_id,
            )
            .outerjoin(SnapshotSeriesPointLinkModel, visible)
            .outerjoin(
                PortfolioSnapshotModel,
                PortfolioSnapshotModel.id == SnapshotSeriesPointLinkModel.portfolio_snapshot_id,
            )
            .where(UserReadModelPublicationModel.user_id == user_id)
            .order_by(
                SnapshotSeriesPointLinkModel.timestamp.desc(),
                SnapshotSeriesPointLinkModel.id.desc(),
            )
        )
        records = tuple((await self.session.execute(statement)).all())
        if not records:
            return (), None, 0
        publication, version = records[0][:2]
        return (
            tuple(
                (snapshot, None, valuation)
                for _, _, snapshot, valuation in records
                if snapshot is not None
            ),
            publication,
            version,
        )

    async def _positions(
        self,
        *,
        rows: _HistoryRows,
        account_id: str | None,
    ) -> dict[str, tuple[PortfolioHistoryPositionResponse, ...]]:
        snapshot_ids = tuple(row[0].id for row in rows)
        if not snapshot_ids:
            return {}
        result: dict[str, list[PortfolioHistoryPositionResponse]] = {}
        if account_id is not None:
            items = tuple(
                (
                    await self.session.scalars(
                        select(AccountSnapshotItemModel)
                        .where(AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids))
                        .order_by(
                            AccountSnapshotItemModel.snapshot_id,
                            AccountSnapshotItemModel.listing_id,
                        )
                    )
                ).all()
            )
            for item in items:
                result.setdefault(item.snapshot_id, []).append(
                    PortfolioHistoryPositionResponse(
                        listing_id=item.listing_id,
                        symbol=item.symbol,
                        quantity=item.quantity,
                        value=item.value,
                        cost_basis=item.cost_basis,
                        allocation_pct=item.allocation_pct,
                        unrealized_pnl_pct=_unrealized_pnl_percentage(
                            value=item.value,
                            cost_basis=item.cost_basis,
                        ),
                        accounts=(
                            PortfolioHistoryPositionAccountResponse(
                                account_id=account_id,
                                quantity=item.quantity,
                                value=item.value,
                                cost_basis=item.cost_basis,
                                allocation_pct=item.allocation_pct,
                            ),
                        ),
                    )
                )
            return {key: tuple(value) for key, value in result.items()}

        portfolio_items = tuple(
            (
                await self.session.scalars(
                    select(PortfolioSnapshotItemModel)
                    .where(PortfolioSnapshotItemModel.portfolio_snapshot_id.in_(snapshot_ids))
                    .order_by(
                        PortfolioSnapshotItemModel.portfolio_snapshot_id,
                        PortfolioSnapshotItemModel.listing_id,
                    )
                )
            ).all()
        )
        item_ids = tuple(portfolio_item.id for portfolio_item in portfolio_items)
        contributions = tuple(
            (
                await self.session.scalars(
                    select(PortfolioSnapshotItemAccountModel)
                    .where(
                        PortfolioSnapshotItemAccountModel.portfolio_snapshot_item_id.in_(item_ids)
                    )
                    .order_by(
                        PortfolioSnapshotItemAccountModel.portfolio_snapshot_item_id,
                        PortfolioSnapshotItemAccountModel.account_id,
                    )
                )
            ).all()
        )
        by_item: dict[str, list[PortfolioHistoryPositionAccountResponse]] = {}
        for contribution in contributions:
            by_item.setdefault(contribution.portfolio_snapshot_item_id, []).append(
                PortfolioHistoryPositionAccountResponse(
                    account_id=contribution.account_id,
                    quantity=contribution.quantity,
                    value=contribution.value,
                    cost_basis=contribution.cost_basis,
                    allocation_pct=contribution.allocation_pct,
                )
            )
        for portfolio_item in portfolio_items:
            result.setdefault(portfolio_item.portfolio_snapshot_id, []).append(
                PortfolioHistoryPositionResponse(
                    listing_id=portfolio_item.listing_id,
                    symbol=portfolio_item.symbol,
                    quantity=portfolio_item.quantity,
                    value=portfolio_item.value,
                    cost_basis=portfolio_item.cost_basis,
                    allocation_pct=portfolio_item.allocation_pct,
                    unrealized_pnl_pct=_unrealized_pnl_percentage(
                        value=portfolio_item.value,
                        cost_basis=portfolio_item.cost_basis,
                    ),
                    accounts=tuple(by_item.get(portfolio_item.id, ())),
                )
            )
        return {key: tuple(value) for key, value in result.items()}

    async def _account_rows(
        self,
        *,
        user_id: str,
        account_id: str,
        cutoff: datetime | None,
    ) -> tuple[
        tuple[tuple[AccountSnapshotModel, AccountSnapshotModel, datetime], ...],
        UserReadModelPublicationModel | None,
        int,
    ]:
        valuation_timestamp = (
            select(func.min(AccountSnapshotItemModel.price_timestamp))
            .where(AccountSnapshotItemModel.snapshot_id == AccountSnapshotModel.id)
            .correlate(AccountSnapshotModel)
            .scalar_subquery()
        )
        statement = (
            select(
                UserReadModelPublicationModel,
                SnapshotSeriesHeadModel.version,
                AccountSnapshotModel,
                valuation_timestamp,
            )
            .join(
                SnapshotSeriesHeadModel,
                SnapshotSeriesHeadModel.id == UserReadModelPublicationModel.series_head_id,
            )
            .outerjoin(
                SnapshotSeriesPointLinkModel,
                (SnapshotSeriesPointLinkModel.user_id == user_id)
                & (
                    SnapshotSeriesPointLinkModel.valid_from_version
                    <= SnapshotSeriesHeadModel.version
                )
                & (
                    SnapshotSeriesPointLinkModel.valid_to_version.is_(None)
                    | (
                        SnapshotSeriesPointLinkModel.valid_to_version
                        > SnapshotSeriesHeadModel.version
                    )
                )
                & (
                    (SnapshotSeriesPointLinkModel.timestamp >= cutoff)
                    if cutoff is not None
                    else True
                ),
            )
            .outerjoin(
                DailySnapshotBaselineAccountModel,
                (
                    SnapshotSeriesPointLinkModel.baseline_id
                    == DailySnapshotBaselineAccountModel.baseline_id
                )
                & (DailySnapshotBaselineAccountModel.account_id == account_id),
            )
            .outerjoin(
                AccountSnapshotModel,
                AccountSnapshotModel.id
                == DailySnapshotBaselineAccountModel.presentation_snapshot_id,
            )
            .where(UserReadModelPublicationModel.user_id == user_id)
            .order_by(
                SnapshotSeriesPointLinkModel.timestamp.desc(),
                SnapshotSeriesPointLinkModel.id.desc(),
            )
        )
        records = tuple((await self.session.execute(statement)).all())
        if not records:
            return (), None, 0
        publication, version = records[0][:2]
        return (
            tuple(
                (
                    snapshot,
                    snapshot,
                    valuation_evidence_timestamp(
                        () if price_timestamp is None else (price_timestamp,),
                        snapshot.exchange_rates,
                        snapshot.calculated_at,
                    ),
                )
                for _, _, snapshot, price_timestamp in records
                if snapshot is not None
            ),
            publication,
            version,
        )

    @staticmethod
    def _select_rows(rows: _HistoryRows) -> _HistoryRows:
        """Keep the full time span while bounding the public chart payload.

        Rows arrive newest first and can contain companion duplicates.  Taking
        only the first 480 made the ``all`` range silently show just the newest
        dense interval.  Deduplicate first, then sample uniformly while always
        retaining both endpoints.
        """

        by_timestamp: dict[datetime, _HistoryRow] = {}
        for row in rows:
            snapshot = row[0]
            by_timestamp.setdefault(snapshot.timestamp, row)
        ordered = tuple(reversed(tuple(by_timestamp.values())))
        if len(ordered) <= _MAX_POINTS:
            return ordered
        indexes = tuple(
            round(index * (len(ordered) - 1) / (_MAX_POINTS - 1)) for index in range(_MAX_POINTS)
        )
        return tuple(ordered[index] for index in indexes)

    @staticmethod
    def _empty(history_range: HistoryPublicRange, currency: str) -> PortfolioHistoryResponse:
        return PortfolioHistoryResponse(
            range=history_range,
            state=PortfolioHistoryReadState.empty,
            currency=currency,
            resolutions=(),
            coverage=(),
            points=(),
        )
