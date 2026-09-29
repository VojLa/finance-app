"""Backfill immutable market valuation evidence for Anycoin BTC transfers."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel
from app.db.models.canonical_lineage import (
    AccountCanonicalChangeModel,
    AccountCanonicalStateModel,
)
from app.db.models.common import QUANTITY
from app.db.models.enums import (
    AccountMemberRole,
    AccountType,
    AssetAliasProvider,
    AssetType,
    ExchangeRateSource,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.ledger import (
    InvestmentEventModel,
    InvestmentMovementModel,
    InvestmentMovementValuationEvidenceModel,
)
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.holdings.rebuild_service import HoldingRebuildService
from app.modules.holdings.repository import HoldingRebuildRepository
from app.modules.investments.transfer_valuation import transfer_valuation_fingerprint
from app.modules.market_data.history.factory import create_local_free_historical_yahoo_providers
from app.modules.market_data.history.models import (
    HistoricalExchangeRateRangeRequirement,
    HistoricalExchangeRateSelection,
    HistoricalMarketEvidenceStateError,
    HistoricalPriceRangeRequirement,
    HistoricalPriceSelection,
    HistoricalTimeSeriesInterval,
)
from app.modules.market_data.history.selection import (
    select_historical_exchange_rates,
    select_historical_prices,
)
from app.modules.market_data.policy import DEFAULT_MARKET_EVIDENCE_POLICY
from app.modules.market_data.source_policy import market_evidence_source_policy_from_settings
from app.modules.market_data.writer import (
    MarketEvidenceWriter,
    PersistMarketEvidenceCommand,
    exchange_rate_id,
    price_snapshot_id,
)
from app.modules.snapshot_refresh.executor import (
    ExecuteUserSnapshotRefreshCommand,
    UserSnapshotRefreshExecutor,
)
from app.shared.canonical_arithmetic import canonical_rounded

_EVIDENCE_NAMESPACE = UUID("80d8a2b5-b8d5-4f61-87f0-455e3fda6c3f")
_CALCULATION_VERSION = 1


class AnycoinTransferValuationConflictError(RuntimeError):
    pass


def _require_same_day_selections(
    price_selections: tuple[HistoricalPriceSelection, ...],
    fx_selections: tuple[HistoricalExchangeRateSelection, ...],
) -> None:
    if any(
        selection.observation.observed_at.date() != selection.through.date()
        for selection in price_selections
    ):
        raise HistoricalMarketEvidenceStateError()


@dataclass(frozen=True, slots=True)
class _Transfer:
    event_id: str
    movement_id: str
    occurred_at: datetime
    quantity: Decimal
    direction: MovementDirection
    asset_id: str
    listing_id: str
    canonical_revision: int


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--email",
        required=True,
        help="Accepted owner email used to select the Anycoin account.",
    )
    parser.add_argument("--account-name", default="AnyCoin")
    parser.add_argument("--publish-at", help="Publish snapshots at this naive ISO timestamp.")
    return parser


async def _load_scope(
    session: AsyncSession, *, email: str, account_name: str
) -> tuple[str, str, str, int, tuple[_Transfer, ...]]:
    statement = select(AccountModel).where(
        AccountModel.name == account_name,
        AccountModel.type == AccountType.exchange,
        AccountModel.is_archived.is_(False),
    )
    statement = statement.join(
        AccountMemberModel, AccountMemberModel.account_id == AccountModel.id
    ).join(UserModel, UserModel.id == AccountMemberModel.user_id)
    statement = statement.where(
        UserModel.email.ilike(email),
        AccountMemberModel.role == AccountMemberRole.owner,
        AccountMemberModel.accepted_at.is_not(None),
    )
    accounts = list((await session.scalars(statement.order_by(AccountModel.id))).unique().all())
    if len(accounts) != 1:
        raise RuntimeError("The requested Anycoin account was not found.")
    account = accounts[0]
    state = await session.get(AccountCanonicalStateModel, account.id)
    if state is None:
        raise RuntimeError("The Anycoin canonical state is unavailable.")
    rows = (
        await session.execute(
            select(InvestmentEventModel, InvestmentMovementModel)
            .join(
                InvestmentMovementModel, InvestmentMovementModel.event_id == InvestmentEventModel.id
            )
            .where(
                InvestmentEventModel.account_id == account.id,
                InvestmentEventModel.source == ImportSource.anycoin,
                InvestmentEventModel.type == InvestmentEventType.asset_transfer,
                InvestmentEventModel.archived_at.is_(None),
                InvestmentEventModel.deleted_at.is_(None),
                InvestmentMovementModel.kind == InvestmentMovementKind.asset,
            )
            .order_by(InvestmentEventModel.date, InvestmentEventModel.id)
        )
    ).all()
    changes = {
        row.entity_id: row
        for row in (
            await session.scalars(
                select(AccountCanonicalChangeModel).where(
                    AccountCanonicalChangeModel.account_id == account.id,
                    AccountCanonicalChangeModel.kind == "investment_event",
                )
            )
        ).all()
    }
    transfers: list[_Transfer] = []
    asset_ids: set[str] = set()
    listing_ids: set[str] = set()
    for event, movement in rows:
        change = changes.get(event.id)
        if (
            change is None
            or change.financial_timestamp != event.date
            or change.revision > state.last_investment_revision
            or movement.asset_id is None
            or movement.listing_id is None
            or movement.direction not in {MovementDirection.incoming, MovementDirection.outgoing}
            or movement.currency != "BTC"
            or movement.source_symbol != "BTC"
            or movement.source_asset_type is not AssetType.crypto
            or movement.quantity <= 0
            or any(
                value is not None
                for value in (
                    movement.price_per_unit,
                    movement.value_amount,
                    movement.value_currency,
                )
            )
        ):
            raise RuntimeError("An Anycoin transfer has an invalid canonical shape.")
        asset_ids.add(movement.asset_id)
        listing_ids.add(movement.listing_id)
        transfers.append(
            _Transfer(
                event_id=event.id,
                movement_id=movement.id,
                occurred_at=event.date,
                quantity=movement.quantity,
                direction=movement.direction,
                asset_id=movement.asset_id,
                listing_id=movement.listing_id,
                canonical_revision=change.revision,
            )
        )
    if not transfers:
        return account.id, "", account.currency, state.last_investment_revision, ()
    if len(asset_ids) != 1 or len(listing_ids) != 1:
        raise RuntimeError("The repair supports one exact BTC identity per account.")
    asset_id = next(iter(asset_ids))
    listing_id = next(iter(listing_ids))
    listing = await session.get(AssetListingModel, listing_id)
    alias = await session.scalar(
        select(AssetAliasModel).where(
            AssetAliasModel.asset_id == asset_id,
            AssetAliasModel.provider == AssetAliasProvider.yahoo_finance,
        )
    )
    if (
        account.currency != "CZK"
        or listing is None
        or listing.currency != account.currency
        or alias is None
        or alias.external_id != "BTC-USD"
    ):
        raise RuntimeError("The exact Anycoin BTC market identity is unavailable.")
    return (
        account.id,
        alias.external_id,
        account.currency,
        state.last_investment_revision,
        tuple(transfers),
    )


def _evidence_matches(
    row: InvestmentMovementValuationEvidenceModel,
    *,
    account_id: str,
    transfer: _Transfer,
    fingerprint: str,
    price: PriceSnapshotModel,
    rate: ExchangeRateModel,
    unit_price: Decimal,
    value_amount: Decimal,
    selection_interval: str,
) -> bool:
    return (
        row.account_id == account_id
        and row.movement_id == transfer.movement_id
        and row.revision == 1
        and row.canonical_revision == transfer.canonical_revision
        and row.effective_at == transfer.occurred_at
        and row.calculation_version == _CALCULATION_VERSION
        and row.selection_interval == selection_interval
        and row.input_fingerprint == fingerprint
        and row.price_snapshot_id == price.id
        and row.exchange_rate_id == rate.id
        and row.price_amount == price.price
        and row.price_currency == price.currency
        and row.price_source is price.source
        and row.price_timestamp == price.timestamp
        and row.fx_rate == rate.rate
        and row.fx_from_currency == rate.from_currency
        and row.fx_to_currency == rate.to_currency
        and row.fx_source is rate.source
        and row.fx_timestamp == rate.date
        and row.price_per_unit == unit_price
        and row.value_amount == value_amount
        and row.value_currency == "CZK"
    )


async def _execute(args: argparse.Namespace) -> None:
    settings = Settings()
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is required.")
    engine = create_async_engine(normalize_database_url(settings.database_url))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            (
                account_id,
                provider_symbol,
                _account_currency,
                captured_investment_revision,
                transfers,
            ) = await _load_scope(session, email=args.email, account_name=args.account_name)
            await session.rollback()
            created_at = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
            created_count = 0
            replayed_count = 0
            if transfers:
                requested_at = tuple(sorted({item.occurred_at for item in transfers}))
                price_provider, fx_provider = create_local_free_historical_yahoo_providers(settings)
                acquisition_error: Exception | None = None
                for interval in (
                    HistoricalTimeSeriesInterval.thirty_minutes,
                    HistoricalTimeSeriesInterval.daily,
                ):
                    try:
                        price_requirement = HistoricalPriceRangeRequirement(
                            asset_id=transfers[0].asset_id,
                            listing_id=transfers[0].listing_id,
                            listing_currency="USD",
                            provider=PriceSource.yahoo_finance,
                            provider_symbol=provider_symbol,
                            requested_at=requested_at,
                            interval=interval,
                        )
                        fx_requirement = HistoricalExchangeRateRangeRequirement(
                            from_currency="USD",
                            to_currency="CZK",
                            provider=ExchangeRateSource.yahoo_finance,
                            requested_at=requested_at,
                            interval=interval,
                        )
                        price_candidates, fx_candidates = await asyncio.gather(
                            price_provider.fetch_range(price_requirement),
                            fx_provider.fetch_range(fx_requirement),
                        )
                        price_selections = select_historical_prices(
                            price_requirement,
                            price_candidates,
                            policy=DEFAULT_MARKET_EVIDENCE_POLICY,
                        )
                        fx_selections = select_historical_exchange_rates(
                            fx_requirement,
                            fx_candidates,
                            policy=DEFAULT_MARKET_EVIDENCE_POLICY,
                        )
                        _require_same_day_selections(price_selections, fx_selections)
                        break
                    except HistoricalMarketEvidenceStateError as exc:
                        acquisition_error = exc
                else:
                    raise RuntimeError(
                        "Anycoin transfer market evidence is unavailable."
                    ) from acquisition_error
                prices_by_time = {item.through: item.observation for item in price_selections}
                rates_by_time = {item.through: item.observation for item in fx_selections}
                unique_prices = {
                    price_snapshot_id(item.observation): item.observation
                    for item in price_selections
                }
                unique_rates = {
                    exchange_rate_id(item.observation): item.observation for item in fx_selections
                }
                await MarketEvidenceWriter(session).write(
                    PersistMarketEvidenceCommand(
                        price_observations=tuple(unique_prices.values()),
                        exchange_rate_observations=tuple(unique_rates.values()),
                        created_at=created_at,
                    )
                )
                async with session.begin():
                    lock_repository = HoldingRebuildRepository(session)
                    await lock_repository.lock_rebuild_scope(account_id)
                    await lock_repository.lock_canonical_history_scopes(account_id)
                    locked_state = await session.scalar(
                        select(AccountCanonicalStateModel)
                        .where(AccountCanonicalStateModel.account_id == account_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    if (
                        locked_state is None
                        or locked_state.last_investment_revision != captured_investment_revision
                    ):
                        raise AnycoinTransferValuationConflictError(
                            "Anycoin canonical history changed during market acquisition."
                        )
                    for transfer in transfers:
                        movement = await session.get(
                            InvestmentMovementModel, transfer.movement_id, with_for_update=True
                        )
                        if (
                            movement is None
                            or movement.event_id != transfer.event_id
                            or movement.quantity != transfer.quantity
                            or movement.direction is not transfer.direction
                            or any(
                                value is not None
                                for value in (
                                    movement.price_per_unit,
                                    movement.value_amount,
                                    movement.value_currency,
                                )
                            )
                        ):
                            raise RuntimeError("Canonical transfer changed during acquisition.")
                        canonical_change = await session.scalar(
                            select(AccountCanonicalChangeModel)
                            .where(
                                AccountCanonicalChangeModel.account_id == account_id,
                                AccountCanonicalChangeModel.kind == "investment_event",
                                AccountCanonicalChangeModel.entity_id == transfer.event_id,
                            )
                            .with_for_update()
                        )
                        if (
                            canonical_change is None
                            or canonical_change.revision != transfer.canonical_revision
                            or canonical_change.financial_timestamp != transfer.occurred_at
                        ):
                            raise RuntimeError(
                                "Canonical transfer lineage changed during acquisition."
                            )
                        selected_price = prices_by_time[transfer.occurred_at]
                        selected_rate = rates_by_time[transfer.occurred_at]
                        selected_price_id = price_snapshot_id(selected_price)
                        selected_rate_id = exchange_rate_id(selected_rate)
                        price = await session.get(PriceSnapshotModel, selected_price_id)
                        rate = await session.get(ExchangeRateModel, selected_rate_id)
                        if (
                            price is None
                            or rate is None
                            or price.asset_id != transfer.asset_id
                            or price.listing_id != transfer.listing_id
                            or price.price != selected_price.price
                            or price.currency != "USD"
                            or price.source is not PriceSource.yahoo_finance
                            or price.timestamp != selected_price.observed_at
                            or rate.rate != selected_rate.rate
                            or rate.from_currency != "USD"
                            or rate.to_currency != "CZK"
                            or rate.source is not ExchangeRateSource.yahoo_finance
                            or rate.date != selected_rate.effective_at
                        ):
                            raise AnycoinTransferValuationConflictError(
                                "Persisted market evidence differs from the selected observation."
                            )
                        fingerprint = transfer_valuation_fingerprint(
                            movement=movement,
                            effective_at=transfer.occurred_at,
                            canonical_revision=transfer.canonical_revision,
                            price_snapshot_id=selected_price_id,
                            exchange_rate_id=selected_rate_id,
                            calculation_version=_CALCULATION_VERSION,
                            selection_interval=interval.value,
                        )
                        unit_price = canonical_rounded(price.price * rate.rate, QUANTITY)
                        value_amount = canonical_rounded(transfer.quantity * unit_price, QUANTITY)
                        existing = list(
                            (
                                await session.scalars(
                                    select(InvestmentMovementValuationEvidenceModel)
                                    .where(
                                        InvestmentMovementValuationEvidenceModel.movement_id
                                        == transfer.movement_id
                                    )
                                    .order_by(InvestmentMovementValuationEvidenceModel.revision)
                                    .with_for_update()
                                )
                            ).all()
                        )
                        if existing:
                            if len(existing) != 1 or not _evidence_matches(
                                existing[0],
                                account_id=account_id,
                                transfer=transfer,
                                fingerprint=fingerprint,
                                price=price,
                                rate=rate,
                                unit_price=unit_price,
                                value_amount=value_amount,
                                selection_interval=interval.value,
                            ):
                                raise AnycoinTransferValuationConflictError(
                                    "Existing Anycoin transfer valuation is not an exact replay."
                                )
                            replayed_count += 1
                            continue
                        session.add(
                            InvestmentMovementValuationEvidenceModel(
                                id=str(uuid5(_EVIDENCE_NAMESPACE, fingerprint)),
                                account_id=account_id,
                                movement_id=transfer.movement_id,
                                revision=1,
                                canonical_revision=transfer.canonical_revision,
                                effective_at=transfer.occurred_at,
                                calculation_version=_CALCULATION_VERSION,
                                selection_interval=interval.value,
                                input_fingerprint=fingerprint,
                                price_snapshot_id=selected_price_id,
                                exchange_rate_id=selected_rate_id,
                                price_amount=price.price,
                                price_currency=price.currency,
                                price_source=price.source,
                                price_timestamp=price.timestamp,
                                fx_rate=rate.rate,
                                fx_from_currency=rate.from_currency,
                                fx_to_currency=rate.to_currency,
                                fx_source=rate.source,
                                fx_timestamp=rate.date,
                                price_per_unit=unit_price,
                                value_amount=value_amount,
                                value_currency="CZK",
                                created_at=created_at,
                            )
                        )
                        created_count += 1
                    await session.flush()
                    rebuilt = await HoldingRebuildService(session).rebuild(
                        account_id=account_id, rebuilt_at=created_at
                    )
            else:
                async with session.begin():
                    rebuilt = await HoldingRebuildService(session).rebuild(
                        account_id=account_id, rebuilt_at=created_at
                    )
            print(
                f"Added {created_count} and replayed {replayed_count} transfer valuation(s); "
                f"rebuilt {rebuilt.total} holding(s) for account {account_id}."
            )

            if args.publish_at:
                publish_at = datetime.fromisoformat(args.publish_at)
                if publish_at.tzinfo is not None or publish_at.microsecond % 1_000:
                    raise RuntimeError("--publish-at must be a naive millisecond ISO timestamp.")
                user_id = await session.scalar(
                    select(UserModel.id).where(UserModel.email.ilike(args.email))
                )
                await session.rollback()
                if not isinstance(user_id, str) or not user_id:
                    raise RuntimeError("The requested user was not found.")
                publication = await UserSnapshotRefreshExecutor(
                    session,
                    source_policy=market_evidence_source_policy_from_settings(settings),
                ).execute(
                    ExecuteUserSnapshotRefreshCommand(
                        user_id=user_id,
                        snapshot_timestamp=publish_at,
                        granularity=SnapshotGranularity.day,
                        source=SnapshotSource.manual_recalculation,
                        calculation_version=3,
                        calculated_at=publish_at,
                        created_at=publish_at,
                        is_recalculated=True,
                    )
                )
                print(
                    f"Published {publication.selected_account_snapshot_count} account snapshot(s) "
                    f"and net-worth snapshot {publication.net_worth_snapshot_id}."
                )
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_execute(_parser().parse_args()))


if __name__ == "__main__":
    main()
