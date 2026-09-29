"""Read-only PostgreSQL boundary for a frozen chronological history replay."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.background_jobs import BackgroundJobModel, ImportJobBatchModel
from app.db.models.canonical_lineage import (
    AccountCanonicalChangeModel,
    AccountCanonicalStateModel,
)
from app.db.models.common import MONEY, TIMESTAMP
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    BackgroundJobKind,
    BackgroundJobStatus,
    ImportStatus,
    InvestmentMovementKind,
    PriceSource,
)
from app.db.models.imports import ImportBatchModel
from app.db.models.ledger import (
    InvestmentEventModel,
    InvestmentMovementModel,
    InvestmentMovementValuationEvidenceModel,
)
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.publication_targets import ImportJobPublicationTargetModel
from app.db.models.transactions import TransactionModel
from app.modules.holdings.persistence_projection import HoldingPersistenceMovement
from app.modules.investments.transfer_valuation import (
    TransferValuationStateError,
    index_latest_transfer_valuations,
    resolve_transfer_valuation,
    validate_transfer_valuation_citations,
)
from app.modules.market_data.requirements import resolve_price_identity
from app.modules.market_data.source_policy import (
    MarketEvidenceSourcePolicy,
    validate_market_evidence_source_policy,
)
from app.modules.portfolio_history_rebuild.models import (
    InvestmentEventRoot,
    LiabilityBalanceRoot,
    ReplayRoot,
    ReplayRootKind,
    TransactionRoot,
    empty_account_replay_state,
)
from app.modules.portfolio_history_rebuild.ordering import canonical_roots, root_timestamp
from app.modules.portfolio_history_rebuild.replay import advance_account_replay
from app.shared.canonical_arithmetic import CanonicalArithmeticError, canonical_rounded

_INVESTMENT_TYPES = {
    AccountType.broker,
    AccountType.exchange,
    AccountType.crypto_wallet,
}
_SUPPORTED_TYPES = frozenset(AccountType)
_ERROR_MESSAGE = "Canonical portfolio history input is unavailable."
_MAX_ACCOUNTS = 10_000
_MAX_CANONICAL_CHANGES = 1_000_000
_MAX_INVESTMENT_MOVEMENTS = 5_000_000
_QUERY_CHUNK_SIZE = 5_000


class PortfolioHistoryReplayRepositoryError(RuntimeError):
    """Persisted rows do not describe one safe, deterministic replay input."""

    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


@dataclass(frozen=True, slots=True)
class FrozenCanonicalRevision:
    last_revision: int
    last_investment_revision: int
    holding_revision: int | None


@dataclass(frozen=True, slots=True)
class FrozenCanonicalChange:
    revision: int
    kind: ReplayRootKind
    entity_id: str
    financial_timestamp: datetime
    included: bool


@dataclass(frozen=True, slots=True)
class FrozenListingIdentity:
    listing_id: str
    asset_id: str
    symbol: str
    name: str | None
    asset_type: str
    currency: str
    price_currency: str
    provider: PriceSource
    provider_symbol: str


@dataclass(frozen=True, slots=True)
class FrozenAccountReplayInput:
    account_id: str
    account_name: str
    account_type: AccountType
    account_currency: str
    canonical_revision: FrozenCanonicalRevision
    canonical_manifest: tuple[FrozenCanonicalChange, ...]
    listing_identities: tuple[FrozenListingIdentity, ...]
    roots: tuple[ReplayRoot, ...]
    earliest_event_at: datetime | None


@dataclass(frozen=True, slots=True)
class FrozenPortfolioReplayInput:
    user_id: str
    base_currency: str
    accounts: tuple[FrozenAccountReplayInput, ...]
    earliest_event_at: datetime | None
    scope_hash: str


def _fail() -> PortfolioHistoryReplayRepositoryError:
    return PortfolioHistoryReplayRepositoryError()


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\0" in value:
        raise _fail()
    return value


def _currency(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 3
        or not value.isascii()
        or not value.isalpha()
        or value != value.upper()
    ):
        raise _fail()
    return value


def _timestamp(value: object) -> datetime:
    precision = TIMESTAMP.precision
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or precision is None
        or value.microsecond % (10 ** (6 - precision))
    ):
        raise _fail()
    return value


def _event_money(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return canonical_rounded(value, MONEY)
    except CanonicalArithmeticError as exc:
        raise _fail() from exc


def _integer(value: object, *, maximum: int | None = None) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or (maximum is not None and value > maximum)
    ):
        raise _fail()
    return value


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(timespec="milliseconds")
    if hasattr(value, "value"):
        return str(value.value)
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _scope_hash(
    *, user_id: str, base_currency: str, accounts: tuple[FrozenAccountReplayInput, ...]
) -> str:
    payload = {
        "version": 1,
        "userId": user_id,
        "baseCurrency": base_currency,
        "accounts": [asdict(account) for account in accounts],
    }
    encoded = json.dumps(
        _json_value(payload),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _kind(value: object) -> ReplayRootKind:
    if not isinstance(value, str):
        raise _fail()
    try:
        return ReplayRootKind(value)
    except (TypeError, ValueError) as exc:
        raise _fail() from exc


def _chunks(values: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(
        values[index : index + _QUERY_CHUNK_SIZE]
        for index in range(0, len(values), _QUERY_CHUNK_SIZE)
    )


def _completed_import_is_visible(
    *,
    batch: ImportBatchModel,
    job: BackgroundJobModel,
    targets: tuple[ImportJobPublicationTargetModel, ...],
) -> bool:
    """Use the importing user's published target as durable account/job proof.

    The current reader's accepted membership authorizes the account separately.
    A target for an unrelated user is not sufficient provenance for this import.
    """

    has_published_target = any(
        target.job_id == job.id
        and target.user_id == job.user_id
        and target.published_at is not None
        for target in targets
    )
    terminal_batch = (
        batch.status in {ImportStatus.completed, ImportStatus.partially_completed}
        and batch.completed_at is not None
    )
    if job.status is BackgroundJobStatus.completed and has_published_target and not terminal_batch:
        raise _fail()
    return bool(
        job.kind is BackgroundJobKind.import_workflow
        and job.status is BackgroundJobStatus.completed
        and terminal_batch
        and has_published_target
    )


class PortfolioHistoryReplayRepository:
    """Load one user's complete replay input under a caller-owned transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        source_policy: MarketEvidenceSourcePolicy,
    ) -> None:
        self.session = session
        self.source_policy = validate_market_evidence_source_policy(source_policy)

    async def set_transaction_repeatable_read_only(self) -> None:
        try:
            await self.session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
        except SQLAlchemyError as exc:
            raise _fail() from exc

    async def load_frozen_scope(self, *, user_id: str) -> FrozenPortfolioReplayInput:
        await self.set_transaction_repeatable_read_only()
        return await self.load_frozen_scope_in_current_transaction(user_id=user_id)

    async def load_frozen_scope_in_current_transaction(
        self, *, user_id: str
    ) -> FrozenPortfolioReplayInput:
        """Freeze through the caller's existing SERIALIZABLE or RR transaction."""

        canonical_user_id = _identifier(user_id)
        if (
            not self.session.in_transaction()
            or self.session.new
            or self.session.dirty
            or self.session.deleted
        ):
            raise _fail()

        user_rows = (
            await self.session.execute(
                text('SELECT "id", "baseCurrency" FROM public."User" WHERE "id" = :id'),
                {"id": canonical_user_id},
            )
        ).all()
        if len(user_rows) != 1 or user_rows[0].id != canonical_user_id:
            raise _fail()
        base_currency = _currency(user_rows[0].baseCurrency)

        access_rows = (
            await self.session.execute(
                select(AccountModel, AccountMemberModel)
                .join(AccountMemberModel, AccountMemberModel.account_id == AccountModel.id)
                .where(
                    AccountMemberModel.user_id == canonical_user_id,
                    AccountMemberModel.accepted_at.is_not(None),
                    AccountModel.is_archived.is_(False),
                )
                .order_by(AccountModel.id)
                .limit(_MAX_ACCOUNTS + 1)
                .execution_options(populate_existing=True, autoflush=False)
            )
        ).all()
        if len(access_rows) > _MAX_ACCOUNTS:
            raise _fail()
        account_rows: list[AccountModel] = []
        membership_ids: set[str] = set()
        for account, membership in access_rows:
            if (
                membership.id in membership_ids
                or membership.account_id != account.id
                or membership.user_id != canonical_user_id
                or not isinstance(membership.role, AccountMemberRole)
                or not isinstance(membership.relation_type, AccountRelationType)
                or membership.accepted_at is None
            ):
                raise _fail()
            _identifier(membership.id)
            _timestamp(membership.accepted_at)
            membership_ids.add(membership.id)
            account_rows.append(account)
        if len({row.id for row in account_rows}) != len(account_rows):
            raise _fail()
        if not account_rows:
            return FrozenPortfolioReplayInput(
                user_id=canonical_user_id,
                base_currency=base_currency,
                accounts=(),
                earliest_event_at=None,
                scope_hash=_scope_hash(
                    user_id=canonical_user_id,
                    base_currency=base_currency,
                    accounts=(),
                ),
            )

        account_ids = tuple(row.id for row in account_rows)
        states = tuple(
            (
                await self.session.scalars(
                    select(AccountCanonicalStateModel)
                    .where(AccountCanonicalStateModel.account_id.in_(account_ids))
                    .order_by(AccountCanonicalStateModel.account_id)
                    .execution_options(populate_existing=True, autoflush=False)
                )
            ).all()
        )
        state_by_account = {state.account_id: state for state in states}
        if len(states) != len(account_ids) or set(state_by_account) != set(account_ids):
            raise _fail()

        changes = tuple(
            (
                await self.session.scalars(
                    select(AccountCanonicalChangeModel)
                    .join(
                        AccountCanonicalStateModel,
                        AccountCanonicalStateModel.account_id
                        == AccountCanonicalChangeModel.account_id,
                    )
                    .where(AccountCanonicalChangeModel.account_id.in_(account_ids))
                    .where(
                        AccountCanonicalChangeModel.revision
                        <= AccountCanonicalStateModel.last_revision
                    )
                    .order_by(
                        AccountCanonicalChangeModel.account_id,
                        AccountCanonicalChangeModel.revision,
                    )
                    .limit(_MAX_CANONICAL_CHANGES + 1)
                    .execution_options(populate_existing=True, autoflush=False)
                )
            ).all()
        )
        if len(changes) > _MAX_CANONICAL_CHANGES:
            raise _fail()
        changes_by_account: defaultdict[str, list[AccountCanonicalChangeModel]] = defaultdict(list)
        changes_by_kind: defaultdict[ReplayRootKind, list[AccountCanonicalChangeModel]] = (
            defaultdict(list)
        )
        identities: set[tuple[ReplayRootKind, str]] = set()
        for change in changes:
            kind = _kind(change.kind)
            if change.account_id not in state_by_account:
                raise _fail()
            identity = (kind, _identifier(change.entity_id))
            if identity in identities:
                raise _fail()
            identities.add(identity)
            changes_by_account[change.account_id].append(change)
            changes_by_kind[kind].append(change)

        transaction_rows = await self._load_transactions(
            changes_by_kind[ReplayRootKind.transaction]
        )
        event_rows = await self._load_investment_events(
            changes_by_kind[ReplayRootKind.investment_event]
        )
        liability_rows = await self._load_liabilities(
            changes_by_kind[ReplayRootKind.liability_balance]
        )

        imported_roots: list[tuple[str, str]] = []
        for transaction_row in transaction_rows.values():
            if transaction_row.import_batch_id is not None:
                imported_roots.append((transaction_row.import_batch_id, transaction_row.account_id))
        for event_row in event_rows.values():
            if event_row.import_batch_id is not None:
                imported_roots.append((event_row.import_batch_id, event_row.account_id))
        import_visibility = await self._load_import_visibility(
            imported_roots=tuple(imported_roots),
        )
        included_event_ids = tuple(
            sorted(
                event.id
                for event in event_rows.values()
                if event.archived_at is None
                and event.deleted_at is None
                and (
                    event.import_batch_id is None
                    or import_visibility.get(event.import_batch_id) is True
                )
            )
        )
        (
            movements_by_event,
            listing_identities,
            transfer_valuations,
        ) = await self._load_investment_details(included_event_ids)

        frozen_accounts: list[FrozenAccountReplayInput] = []
        all_earliest: list[datetime] = []
        for account in account_rows:
            frozen = self._freeze_account(
                account=account,
                state=state_by_account[account.id],
                changes=tuple(changes_by_account[account.id]),
                transaction_rows=transaction_rows,
                event_rows=event_rows,
                movements_by_event=movements_by_event,
                liability_rows=liability_rows,
                listing_identities=listing_identities,
                import_visibility=import_visibility,
                transfer_valuations=transfer_valuations,
            )
            frozen_accounts.append(frozen)
            if frozen.earliest_event_at is not None:
                all_earliest.append(frozen.earliest_event_at)
        accounts = tuple(frozen_accounts)
        return FrozenPortfolioReplayInput(
            user_id=canonical_user_id,
            base_currency=base_currency,
            accounts=accounts,
            earliest_event_at=min(all_earliest) if all_earliest else None,
            scope_hash=_scope_hash(
                user_id=canonical_user_id,
                base_currency=base_currency,
                accounts=accounts,
            ),
        )

    async def _load_transactions(
        self, changes: list[AccountCanonicalChangeModel]
    ) -> dict[str, TransactionModel]:
        ids = tuple(change.entity_id for change in changes)
        if not ids:
            return {}
        rows: list[TransactionModel] = []
        for chunk in _chunks(ids):
            rows.extend(
                (
                    await self.session.scalars(
                        select(TransactionModel)
                        .where(TransactionModel.id.in_(chunk))
                        .order_by(TransactionModel.id)
                        .execution_options(populate_existing=True, autoflush=False)
                    )
                ).all()
            )
        result = {row.id: row for row in rows}
        if len(rows) != len(ids) or set(result) != set(ids):
            raise _fail()
        return result

    async def _load_investment_events(
        self, changes: list[AccountCanonicalChangeModel]
    ) -> dict[str, InvestmentEventModel]:
        ids = tuple(change.entity_id for change in changes)
        if not ids:
            return {}
        events: list[InvestmentEventModel] = []
        for chunk in _chunks(ids):
            events.extend(
                (
                    await self.session.scalars(
                        select(InvestmentEventModel)
                        .where(InvestmentEventModel.id.in_(chunk))
                        .order_by(InvestmentEventModel.id)
                        .execution_options(populate_existing=True, autoflush=False)
                    )
                ).all()
            )
        event_by_id = {row.id: row for row in events}
        if len(events) != len(ids) or set(event_by_id) != set(ids):
            raise _fail()
        return event_by_id

    async def _load_investment_details(
        self, event_ids: tuple[str, ...]
    ) -> tuple[
        dict[str, tuple[InvestmentMovementModel, ...]],
        dict[str, FrozenListingIdentity],
        dict[str, InvestmentMovementValuationEvidenceModel],
    ]:
        if not event_ids:
            return {}, {}, {}
        movements: list[InvestmentMovementModel] = []
        for chunk in _chunks(event_ids):
            remaining = _MAX_INVESTMENT_MOVEMENTS + 1 - len(movements)
            if remaining <= 0:
                raise _fail()
            movements.extend(
                (
                    await self.session.scalars(
                        select(InvestmentMovementModel)
                        .where(InvestmentMovementModel.event_id.in_(chunk))
                        .order_by(InvestmentMovementModel.event_id, InvestmentMovementModel.id)
                        .limit(remaining)
                        .execution_options(populate_existing=True, autoflush=False)
                    )
                ).all()
            )
        if len(movements) > _MAX_INVESTMENT_MOVEMENTS:
            raise _fail()
        movement_ids: set[str] = set()
        grouped: defaultdict[str, list[InvestmentMovementModel]] = defaultdict(list)
        listing_ids: set[str] = set()
        event_id_set = set(event_ids)
        for movement in movements:
            if movement.id in movement_ids or movement.event_id not in event_id_set:
                raise _fail()
            movement_ids.add(movement.id)
            grouped[movement.event_id].append(movement)
            if movement.listing_id is not None:
                listing_ids.add(movement.listing_id)
        if any(not grouped[event_id] for event_id in event_ids):
            raise _fail()
        identities: dict[str, FrozenListingIdentity] = {}
        if listing_ids:
            persisted: dict[str, tuple[AssetListingModel, AssetModel]] = {}
            for chunk in _chunks(tuple(sorted(listing_ids))):
                rows = (
                    await self.session.execute(
                        select(AssetListingModel, AssetModel)
                        .join(AssetModel, AssetModel.id == AssetListingModel.asset_id)
                        .where(AssetListingModel.id.in_(chunk))
                        .order_by(AssetListingModel.id)
                        .execution_options(populate_existing=True, autoflush=False)
                    )
                ).all()
                for listing, asset in rows:
                    if listing.id in persisted or listing.asset_id != asset.id:
                        raise _fail()
                    persisted[listing.id] = (listing, asset)
            if set(persisted) != listing_ids:
                raise _fail()
            asset_ids = tuple(sorted({asset.id for _, asset in persisted.values()}))
            aliases_by_asset: defaultdict[str, list[AssetAliasModel]] = defaultdict(list)
            for chunk in _chunks(asset_ids):
                aliases = (
                    await self.session.scalars(
                        select(AssetAliasModel)
                        .where(AssetAliasModel.asset_id.in_(chunk))
                        .order_by(
                            AssetAliasModel.asset_id,
                            AssetAliasModel.provider,
                            AssetAliasModel.external_id,
                            AssetAliasModel.id,
                        )
                        .execution_options(populate_existing=True, autoflush=False)
                    )
                ).all()
                for alias in aliases:
                    aliases_by_asset[alias.asset_id].append(alias)
            for listing_id in sorted(persisted):
                listing, asset = persisted[listing_id]
                try:
                    provider_identity = resolve_price_identity(
                        listing=listing,
                        asset=asset,
                        aliases=tuple(aliases_by_asset[asset.id]),
                        supported_sources=self.source_policy.price_sources,
                        source_policy=self.source_policy,
                    )
                except (TypeError, ValueError) as exc:
                    raise _fail() from exc
                identities[listing.id] = FrozenListingIdentity(
                    listing_id=_identifier(listing.id),
                    asset_id=_identifier(asset.id),
                    symbol=_identifier(asset.symbol),
                    name=asset.name,
                    asset_type=asset.asset_type.value,
                    currency=_currency(listing.currency),
                    price_currency=_currency(provider_identity.price_currency),
                    provider=provider_identity.provider,
                    provider_symbol=_identifier(provider_identity.provider_symbol),
                )
        valuation_rows: list[InvestmentMovementValuationEvidenceModel] = []
        for chunk in _chunks(tuple(sorted(movement_ids))):
            joined_rows = (
                await self.session.execute(
                    select(
                        InvestmentMovementValuationEvidenceModel,
                        PriceSnapshotModel,
                        ExchangeRateModel,
                        InvestmentMovementModel,
                    )
                    .join(
                        PriceSnapshotModel,
                        PriceSnapshotModel.id
                        == InvestmentMovementValuationEvidenceModel.price_snapshot_id,
                    )
                    .outerjoin(
                        ExchangeRateModel,
                        ExchangeRateModel.id
                        == InvestmentMovementValuationEvidenceModel.exchange_rate_id,
                    )
                    .join(
                        InvestmentMovementModel,
                        InvestmentMovementModel.id
                        == InvestmentMovementValuationEvidenceModel.movement_id,
                    )
                    .where(InvestmentMovementValuationEvidenceModel.movement_id.in_(chunk))
                    .order_by(
                        InvestmentMovementValuationEvidenceModel.movement_id,
                        InvestmentMovementValuationEvidenceModel.revision,
                    )
                    .execution_options(populate_existing=True, autoflush=False)
                )
            ).all()
            for evidence, price, rate, movement in joined_rows:
                validate_transfer_valuation_citations(
                    evidence=evidence,
                    movement=movement,
                    price=price,
                    exchange_rate=rate,
                )
                valuation_rows.append(evidence)
        try:
            transfer_valuations = index_latest_transfer_valuations(valuation_rows)
        except TransferValuationStateError as exc:
            raise _fail() from exc
        return (
            {event_id: tuple(rows) for event_id, rows in grouped.items()},
            identities,
            transfer_valuations,
        )

    async def _load_liabilities(
        self, changes: list[AccountCanonicalChangeModel]
    ) -> dict[str, LiabilityBalanceModel]:
        ids = tuple(change.entity_id for change in changes)
        if not ids:
            return {}
        rows: list[LiabilityBalanceModel] = []
        for chunk in _chunks(ids):
            rows.extend(
                (
                    await self.session.scalars(
                        select(LiabilityBalanceModel)
                        .where(LiabilityBalanceModel.id.in_(chunk))
                        .order_by(LiabilityBalanceModel.id)
                        .execution_options(populate_existing=True, autoflush=False)
                    )
                ).all()
            )
        result = {row.id: row for row in rows}
        if len(rows) != len(ids) or set(result) != set(ids):
            raise _fail()
        return result

    async def _load_import_visibility(
        self,
        *,
        imported_roots: tuple[tuple[str, str], ...],
    ) -> dict[str, bool]:
        if not imported_roots:
            return {}
        expected_accounts: defaultdict[str, set[str]] = defaultdict(set)
        for batch_id, account_id in imported_roots:
            expected_accounts[_identifier(batch_id)].add(_identifier(account_id))
        if any(len(accounts) != 1 for accounts in expected_accounts.values()):
            raise _fail()
        batch_ids = tuple(sorted(expected_accounts))
        batches: list[ImportBatchModel] = []
        for chunk in _chunks(batch_ids):
            batches.extend(
                (
                    await self.session.scalars(
                        select(ImportBatchModel)
                        .where(ImportBatchModel.id.in_(chunk))
                        .order_by(ImportBatchModel.id)
                        .execution_options(populate_existing=True, autoflush=False)
                    )
                ).all()
            )
        batch_by_id = {batch.id: batch for batch in batches}
        if len(batches) != len(batch_ids) or set(batch_by_id) != set(batch_ids):
            raise _fail()
        if any(batch.account_id not in expected_accounts[batch.id] for batch in batches):
            raise _fail()

        provenance_rows: list[tuple[ImportJobBatchModel, BackgroundJobModel]] = []
        for chunk in _chunks(batch_ids):
            remaining = _MAX_CANONICAL_CHANGES + 1 - len(provenance_rows)
            if remaining <= 0:
                raise _fail()
            result = await self.session.execute(
                select(ImportJobBatchModel, BackgroundJobModel)
                .join(
                    BackgroundJobModel,
                    BackgroundJobModel.id == ImportJobBatchModel.job_id,
                )
                .where(ImportJobBatchModel.batch_id.in_(chunk))
                .order_by(ImportJobBatchModel.batch_id, ImportJobBatchModel.job_id)
                .limit(remaining)
                .execution_options(populate_existing=True, autoflush=False)
            )
            provenance_rows.extend((link, job) for link, job in result.all())
        if len(provenance_rows) > _MAX_CANONICAL_CHANGES:
            raise _fail()
        provenance: defaultdict[str, list[BackgroundJobModel]] = defaultdict(list)
        for link, job in provenance_rows:
            batch = batch_by_id.get(link.batch_id)
            if (
                batch is None
                or link.account_id != batch.account_id
                or link.user_id != batch.user_id
                or job.id != link.job_id
                or job.account_id != batch.account_id
                or job.user_id != batch.user_id
            ):
                raise _fail()
            provenance[link.batch_id].append(job)
        if any(len(provenance[batch_id]) > 1 for batch_id in batch_ids):
            raise _fail()
        job_ids = tuple(
            provenance[batch_id][0].id for batch_id in batch_ids if provenance[batch_id]
        )
        targets: list[ImportJobPublicationTargetModel] = []
        for chunk in _chunks(job_ids):
            targets.extend(
                (
                    await self.session.scalars(
                        select(ImportJobPublicationTargetModel)
                        .where(ImportJobPublicationTargetModel.job_id.in_(chunk))
                        .order_by(
                            ImportJobPublicationTargetModel.job_id,
                            ImportJobPublicationTargetModel.user_id,
                        )
                        .execution_options(populate_existing=True, autoflush=False)
                    )
                ).all()
            )
        targets_by_job: defaultdict[str, list[ImportJobPublicationTargetModel]] = defaultdict(list)
        expected_job_ids = set(job_ids)
        for target in targets:
            if target.job_id not in expected_job_ids:
                raise _fail()
            _identifier(target.user_id)
            _timestamp(target.bucket)
            if target.published_at is not None:
                _timestamp(target.published_at)
            targets_by_job[target.job_id].append(target)
        visibility: dict[str, bool] = {}
        for batch_id in batch_ids:
            if not provenance[batch_id]:
                visibility[batch_id] = False
                continue
            job = provenance[batch_id][0]
            job_targets = tuple(targets_by_job[job.id])
            batch = batch_by_id[batch_id]
            visibility[batch_id] = _completed_import_is_visible(
                batch=batch,
                job=job,
                targets=job_targets,
            )
        return visibility

    def _freeze_account(
        self,
        *,
        account: AccountModel,
        state: AccountCanonicalStateModel,
        changes: tuple[AccountCanonicalChangeModel, ...],
        transaction_rows: dict[str, TransactionModel],
        event_rows: dict[str, InvestmentEventModel],
        movements_by_event: dict[str, tuple[InvestmentMovementModel, ...]],
        liability_rows: dict[str, LiabilityBalanceModel],
        listing_identities: dict[str, FrozenListingIdentity],
        import_visibility: dict[str, bool],
        transfer_valuations: dict[str, InvestmentMovementValuationEvidenceModel],
    ) -> FrozenAccountReplayInput:
        account_id = _identifier(account.id)
        if (
            account.is_archived
            or account.archived_at is not None
            or not isinstance(account.type, AccountType)
        ):
            raise _fail()
        if account.type not in _SUPPORTED_TYPES:
            raise _fail()
        account_currency = _currency(account.currency)
        last_revision = _integer(state.last_revision)
        last_investment = _integer(state.last_investment_revision, maximum=last_revision)
        holding_revision = (
            None
            if state.holding_revision is None
            else _integer(state.holding_revision, maximum=last_investment)
        )
        if state.account_id != account_id or len(changes) != last_revision:
            raise _fail()
        expected_revisions = tuple(range(1, last_revision + 1))
        if tuple(change.revision for change in changes) != expected_revisions:
            raise _fail()
        investment_revisions = tuple(
            change.revision for change in changes if change.kind == ReplayRootKind.investment_event
        )
        if (investment_revisions[-1] if investment_revisions else 0) != last_investment:
            raise _fail()
        if account.type in _INVESTMENT_TYPES and holding_revision != last_investment:
            raise _fail()

        roots: list[ReplayRoot] = []
        manifest: list[FrozenCanonicalChange] = []
        used_listing_ids: set[str] = set()
        for change in changes:
            kind = _kind(change.kind)
            financial_timestamp = _timestamp(change.financial_timestamp)
            entity_id = _identifier(change.entity_id)
            included = False
            root: ReplayRoot
            if kind is ReplayRootKind.transaction:
                transaction_row = transaction_rows.get(entity_id)
                if (
                    transaction_row is None
                    or transaction_row.account_id != account_id
                    or _timestamp(transaction_row.date) != financial_timestamp
                ):
                    raise _fail()
                included = (
                    transaction_row.archived_at is None
                    and transaction_row.deleted_at is None
                    and (
                        transaction_row.import_batch_id is None
                        or import_visibility.get(transaction_row.import_batch_id) is True
                    )
                )
                if not included:
                    manifest.append(
                        FrozenCanonicalChange(
                            revision=change.revision,
                            kind=kind,
                            entity_id=entity_id,
                            financial_timestamp=financial_timestamp,
                            included=False,
                        )
                    )
                    continue
                if transaction_row.classification is None:
                    raise _fail()
                root = TransactionRoot(
                    transaction_id=_identifier(transaction_row.id),
                    account_id=account_id,
                    timestamp=financial_timestamp,
                    amount=transaction_row.amount,
                    currency=transaction_row.currency,
                    transaction_type=transaction_row.type,
                    classification=transaction_row.classification,
                    eligible=True,
                )
            elif kind is ReplayRootKind.investment_event:
                event_row = event_rows.get(entity_id)
                if (
                    event_row is None
                    or event_row.account_id != account_id
                    or _timestamp(event_row.date) != financial_timestamp
                ):
                    raise _fail()
                included = (
                    event_row.archived_at is None
                    and event_row.deleted_at is None
                    and (
                        event_row.import_batch_id is None
                        or import_visibility.get(event_row.import_batch_id) is True
                    )
                )
                if not included:
                    manifest.append(
                        FrozenCanonicalChange(
                            revision=change.revision,
                            kind=kind,
                            entity_id=entity_id,
                            financial_timestamp=financial_timestamp,
                            included=False,
                        )
                    )
                    continue
                movements: list[HoldingPersistenceMovement] = []
                for movement in movements_by_event.get(event_row.id, ()):
                    if movement.account_id != account_id or movement.event_id != event_row.id:
                        raise _fail()
                    identity = (
                        None
                        if movement.listing_id is None
                        else listing_identities.get(movement.listing_id)
                    )
                    if movement.listing_id is not None and identity is None:
                        raise _fail()
                    if identity is not None:
                        used_listing_ids.add(identity.listing_id)
                        if (
                            movement.asset_id != identity.asset_id
                            or movement.source_symbol != identity.symbol
                            or movement.source_asset_type is None
                            or movement.source_asset_type.value != identity.asset_type
                        ):
                            raise _fail()
                    if movement.kind is InvestmentMovementKind.asset and identity is None:
                        raise _fail()
                    try:
                        valuation = resolve_transfer_valuation(
                            event=event_row,
                            movement=movement,
                            evidence=transfer_valuations.get(movement.id),
                            canonical_revision=change.revision,
                        )
                    except TransferValuationStateError as exc:
                        raise _fail() from exc
                    movements.append(
                        HoldingPersistenceMovement(
                            movement_id=_identifier(movement.id),
                            event_id=_identifier(movement.event_id),
                            account_id=account_id,
                            kind=movement.kind,
                            direction=movement.direction,
                            quantity=movement.quantity,
                            currency=movement.currency,
                            asset_id=movement.asset_id,
                            listing_id=movement.listing_id,
                            listing_asset_id=None if identity is None else identity.asset_id,
                            source_symbol=movement.source_symbol,
                            source_asset_type=movement.source_asset_type,
                            price_per_unit=(
                                valuation.price_per_unit
                                if valuation is not None
                                else movement.price_per_unit
                            ),
                            value_amount=(
                                valuation.value_amount
                                if valuation is not None
                                else movement.value_amount
                            ),
                            value_currency=(
                                valuation.value_currency
                                if valuation is not None
                                else movement.value_currency
                            ),
                            listing_currency=None if identity is None else identity.currency,
                        )
                    )
                root = InvestmentEventRoot(
                    event_id=_identifier(event_row.id),
                    account_id=account_id,
                    event_type=event_row.type,
                    event_date=financial_timestamp,
                    movements=tuple(movements),
                    source=event_row.source,
                    external_id=event_row.external_id,
                    realized_pnl=_event_money(event_row.realized_pnl),
                    realized_pnl_currency=event_row.realized_pnl_currency,
                    eligible=True,
                )
            else:
                liability_row = liability_rows.get(entity_id)
                if (
                    liability_row is None
                    or liability_row.account_id != account_id
                    or _timestamp(liability_row.effective_at) != financial_timestamp
                    or liability_row.total_outstanding
                    != liability_row.outstanding_principal
                    + liability_row.accrued_interest
                    + liability_row.fees_outstanding
                ):
                    raise _fail()
                included = True
                root = LiabilityBalanceRoot(
                    balance_id=_identifier(liability_row.id),
                    account_id=account_id,
                    effective_at=financial_timestamp,
                    currency=liability_row.currency,
                    outstanding_principal=liability_row.outstanding_principal,
                    accrued_interest=liability_row.accrued_interest,
                    fees_outstanding=liability_row.fees_outstanding,
                    eligible=True,
                )
            manifest.append(
                FrozenCanonicalChange(
                    revision=change.revision,
                    kind=kind,
                    entity_id=entity_id,
                    financial_timestamp=financial_timestamp,
                    included=included,
                )
            )
            if included:
                roots.append(root)

        canonical = canonical_roots(tuple(roots))
        try:
            advance_account_replay(
                empty_account_replay_state(
                    account_id=account_id,
                    account_type=account.type,
                    account_currency=account_currency,
                ),
                canonical,
            )
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise _fail() from exc
        earliest = min((root_timestamp(root) for root in canonical), default=None)
        identities = tuple(
            listing_identities[listing_id] for listing_id in sorted(used_listing_ids)
        )
        return FrozenAccountReplayInput(
            account_id=account_id,
            account_name=_identifier(account.name),
            account_type=account.type,
            account_currency=account_currency,
            canonical_revision=FrozenCanonicalRevision(
                last_revision=last_revision,
                last_investment_revision=last_investment,
                holding_revision=holding_revision,
            ),
            canonical_manifest=tuple(manifest),
            listing_identities=identities,
            roots=canonical,
            earliest_event_at=earliest,
        )


__all__ = [
    "FrozenAccountReplayInput",
    "FrozenCanonicalChange",
    "FrozenCanonicalRevision",
    "FrozenListingIdentity",
    "FrozenPortfolioReplayInput",
    "PortfolioHistoryReplayRepository",
    "PortfolioHistoryReplayRepositoryError",
]
