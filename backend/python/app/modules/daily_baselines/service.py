from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.background_jobs import BackgroundJobModel
from app.db.models.canonical_lineage import (
    AccountCanonicalChangeModel,
    AccountCanonicalStateModel,
    AccountSnapshotCanonicalBoundaryModel,
    DailySnapshotBaselineAccountModel,
    DailySnapshotBaselineModel,
)
from app.db.models.common import TIMESTAMP
from app.db.models.enums import (
    AccountType,
    BackgroundJobKind,
    BackgroundJobStatus,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.ledger import InvestmentEventModel
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.publication_targets import ImportJobPublicationTargetModel
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.modules.net_worth.evidence_service import (
    BuildNetWorthEvidenceCommand,
    NetWorthEvidenceService,
    NetWorthEvidenceStateError,
    SelectedAccountSnapshotIdentity,
)
from app.modules.net_worth.persistence_projection import (
    NetWorthSnapshotPersistenceMetadata,
    NetWorthSnapshotPersistenceProjectionError,
    build_net_worth_snapshot_persistence_projection,
)

_BASELINE_NAMESPACE = UUID("f391a7b0-8d0c-5dd9-9db3-72f8064dbebf")
_STATE_MESSAGE = "Daily snapshot baseline evidence is unavailable."
_BIGINT_MAX = 9_223_372_036_854_775_807
_INVESTMENT_TYPES = {AccountType.broker, AccountType.exchange, AccountType.crypto_wallet}
_LIABILITY_TYPES = {AccountType.credit_card, AccountType.loan, AccountType.mortgage}
_SUPPORTED_TYPES = set(AccountType)
_RETRYABLE_SQLSTATES = {"40001", "40P01", "23505"}
_MAX_TRANSACTION_ATTEMPTS = 3


class DailyBaselineError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(_STATE_MESSAGE)


class DailyBaselineUnavailableError(DailyBaselineError):
    pass


class DailyBaselineDisposition(StrEnum):
    created = "created"
    replayed = "replayed"


@dataclass(frozen=True, slots=True)
class PersistDailySnapshotBaselineCommand:
    user_id: str
    net_worth_snapshot_id: str
    timestamp: datetime
    currency: str
    calculation_version: int
    source: SnapshotSource
    created_at: datetime
    primary_snapshot_identities: tuple[SelectedAccountSnapshotIdentity, ...]
    granularity: SnapshotGranularity = SnapshotGranularity.day
    publication_job_id: str | None = None


@dataclass(frozen=True, slots=True)
class PersistDailySnapshotBaselineResult:
    baseline_id: str
    net_worth_snapshot_id: str
    account_count: int
    disposition: DailyBaselineDisposition


@dataclass(frozen=True, slots=True)
class DailyBaselineAccount:
    account_id: str
    account_type: AccountType
    account_currency: str
    primary_snapshot_id: str
    presentation_snapshot_id: str
    canonical_revision: int
    investment_revision: int | None
    holding_revision: int | None
    selected_liability_balance_id: str | None


@dataclass(frozen=True, slots=True)
class DailyBaselineChange:
    account_id: str
    revision: int
    kind: str
    entity_id: str
    financial_timestamp: datetime


@dataclass(frozen=True, slots=True)
class DailySnapshotBaseline:
    baseline_id: str
    user_id: str
    net_worth_snapshot_id: str
    timestamp: datetime
    currency: str
    calculation_version: int
    source: SnapshotSource
    accounts: tuple[DailyBaselineAccount, ...]
    post_baseline_changes: tuple[DailyBaselineChange, ...]
    granularity: SnapshotGranularity = SnapshotGranularity.day
    publication_job_id: str | None = None


def freeze_baseline_post_changes(
    baseline: DailySnapshotBaseline,
    *,
    account_ids: tuple[str, ...],
) -> DailySnapshotBaseline:
    """Keep the published baseline for accounts with an unpublished import job.

    An import can commit canonical rows before its coordinated snapshot
    publication succeeds.  Those rows must not become a read-time delta until
    the durable job has left its active lifecycle.  This helper intentionally
    keeps the original immutable baseline identity and only removes forward
    changes for the affected accounts.
    """

    frozen = frozenset(_text(account_id) for account_id in account_ids)
    if not frozen:
        return baseline
    return replace(
        baseline,
        post_baseline_changes=tuple(
            change for change in baseline.post_baseline_changes if change.account_id not in frozen
        ),
    )


def _fail() -> DailyBaselineError:
    return DailyBaselineError()


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\0" in value:
        raise _fail()
    return value


def _currency(value: object) -> str:
    result = _text(value)
    if len(result) != 3 or not result.isascii() or not result.isalpha() or result != result.upper():
        raise _fail()
    return result


def _timestamp(value: object) -> datetime:
    precision = TIMESTAMP.precision
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or precision is None
        or not 0 <= precision <= 6
        or value.microsecond % (10 ** (6 - precision))
    ):
        raise _fail()
    return value


def _revision(value: object, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= _BIGINT_MAX:
        raise _fail()
    return value


def _version(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 < value <= 2_147_483_647:
        raise _fail()
    return value


def _baseline_id(net_worth_snapshot_id: str) -> str:
    return str(uuid5(_BASELINE_NAMESPACE, _text(net_worth_snapshot_id)))


def _publication_granularity(
    granularity: object,
    source: object,
) -> SnapshotGranularity:
    if not isinstance(granularity, SnapshotGranularity) or not isinstance(source, SnapshotSource):
        raise _fail()
    if granularity is SnapshotGranularity.day:
        return granularity
    if granularity is SnapshotGranularity.minute and source is SnapshotSource.import_event:
        return granularity
    raise _fail()


def _publication_job_id(
    value: object,
    *,
    granularity: SnapshotGranularity,
) -> str | None:
    if granularity is SnapshotGranularity.day:
        if value is not None:
            raise _fail()
        return None
    if granularity is SnapshotGranularity.minute:
        return _text(value)
    raise _fail()


def _aligned_publication_timestamp(
    timestamp: object,
    granularity: SnapshotGranularity,
) -> datetime:
    value = _timestamp(timestamp)
    if granularity is SnapshotGranularity.day and value.time() == datetime.min.time():
        return value
    if granularity is SnapshotGranularity.minute and value.second == 0 and value.microsecond == 0:
        return value
    raise _fail()


def _published_baseline_query(*, user_id: str, through: datetime):
    return (
        select(DailySnapshotBaselineModel)
        .outerjoin(
            ImportJobPublicationTargetModel,
            (DailySnapshotBaselineModel.background_job_id == ImportJobPublicationTargetModel.job_id)
            & (DailySnapshotBaselineModel.user_id == ImportJobPublicationTargetModel.user_id),
        )
        .outerjoin(
            BackgroundJobModel,
            DailySnapshotBaselineModel.background_job_id == BackgroundJobModel.id,
        )
        .where(
            DailySnapshotBaselineModel.user_id == user_id,
            DailySnapshotBaselineModel.timestamp <= through,
            (DailySnapshotBaselineModel.background_job_id.is_(None))
            | (
                (BackgroundJobModel.status == BackgroundJobStatus.completed)
                & (ImportJobPublicationTargetModel.published_at.is_not(None))
            ),
        )
        .order_by(
            DailySnapshotBaselineModel.timestamp.desc(),
            DailySnapshotBaselineModel.id.desc(),
        )
        .limit(1)
    )


def _lock_id(scope: str) -> int:
    return int.from_bytes(sha256(scope.encode()).digest()[:8], "big", signed=True)


def _sqlstate(error: BaseException) -> str | None:
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        candidate = pending.pop()
        if id(candidate) in seen:
            continue
        seen.add(id(candidate))
        for attribute in ("sqlstate", "pgcode"):
            value = getattr(candidate, attribute, None)
            if isinstance(value, str):
                return value
        for attribute in ("orig", "__cause__", "__context__"):
            nested = getattr(candidate, attribute, None)
            if isinstance(nested, BaseException):
                pending.append(nested)
    return None


def _boundary_account(
    *,
    account: AccountModel,
    primary: AccountSnapshotModel,
    presentation: AccountSnapshotModel,
    primary_boundary: AccountSnapshotCanonicalBoundaryModel,
    presentation_boundary: AccountSnapshotCanonicalBoundaryModel,
    granularity: SnapshotGranularity,
) -> DailyBaselineAccount:
    if (
        account.id != primary.account_id
        or account.id != presentation.account_id
        or primary.timestamp != presentation.timestamp
        or primary.granularity is not granularity
        or presentation.granularity is not granularity
        or primary.source is not presentation.source
        or primary.calculation_version != presentation.calculation_version
        or primary_boundary.snapshot_id != primary.id
        or presentation_boundary.snapshot_id != presentation.id
        or primary_boundary.account_id != account.id
        or presentation_boundary.account_id != account.id
        or primary_boundary.canonical_revision != presentation_boundary.canonical_revision
        or primary_boundary.investment_revision != presentation_boundary.investment_revision
        or primary_boundary.holding_revision != presentation_boundary.holding_revision
        or primary_boundary.selected_liability_balance_id
        != presentation_boundary.selected_liability_balance_id
    ):
        raise _fail()
    canonical = _revision(primary_boundary.canonical_revision)
    investment = primary_boundary.investment_revision
    holding = primary_boundary.holding_revision
    liability = primary_boundary.selected_liability_balance_id
    if account.type in _INVESTMENT_TYPES:
        if investment is None or holding is None:
            raise _fail()
        investment = _revision(investment)
        holding = _revision(holding)
        if investment != holding or investment > canonical or liability is not None:
            raise _fail()
    elif account.type in _LIABILITY_TYPES:
        if investment is not None or holding is not None or liability is None:
            raise _fail()
        liability = _text(liability)
    elif account.type in _SUPPORTED_TYPES:
        if investment is not None or holding is not None or liability is not None:
            raise _fail()
    else:
        raise _fail()
    return DailyBaselineAccount(
        account_id=_text(account.id),
        account_type=account.type,
        account_currency=_currency(account.currency),
        primary_snapshot_id=_text(primary.id),
        presentation_snapshot_id=_text(presentation.id),
        canonical_revision=canonical,
        investment_revision=investment,
        holding_revision=holding,
        selected_liability_balance_id=liability,
    )


_NET_WORTH_ATTRIBUTES = (
    "id",
    "user_id",
    "timestamp",
    "granularity",
    "source",
    "currency",
    "cash_value",
    "portfolio_value",
    "liabilities_value",
    "total_net_worth",
    "is_recalculated",
    "calculated_at",
    "calculation_version",
    "created_at",
    "cash_value_by_currency",
    "portfolio_value_by_currency",
    "liabilities_value_by_currency",
    "total_net_worth_by_currency",
    "exchange_rates",
)


async def _validate_net_worth_graph(
    session: AsyncSession,
    *,
    net_worth: NetWorthSnapshotModel,
    identities: tuple[SelectedAccountSnapshotIdentity, ...],
) -> None:
    try:
        evidence = await NetWorthEvidenceService(session).build(
            BuildNetWorthEvidenceCommand(
                user_id=net_worth.user_id,
                timestamp=net_worth.timestamp,
                granularity=net_worth.granularity,
                currency=net_worth.currency,
                calculation_version=net_worth.calculation_version,
                required_account_snapshot_identities=identities,
            )
        )
        expected = build_net_worth_snapshot_persistence_projection(
            evidence,
            NetWorthSnapshotPersistenceMetadata(
                source=net_worth.source,
                calculated_at=net_worth.calculated_at,
                created_at=net_worth.created_at,
                is_recalculated=net_worth.is_recalculated,
            ),
        ).snapshot
    except (NetWorthEvidenceStateError, NetWorthSnapshotPersistenceProjectionError) as exc:
        raise _fail() from exc
    values = expected.model_values()
    if any(getattr(net_worth, name) != values[name] for name in _NET_WORTH_ATTRIBUTES):
        raise _fail()


class DailySnapshotBaselineService:
    """Persist and select exact D1 lineage without projecting current finance."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def persist(
        self, command: PersistDailySnapshotBaselineCommand
    ) -> PersistDailySnapshotBaselineResult:
        if self.session.in_transaction():
            raise _fail()
        for attempt in range(_MAX_TRANSACTION_ATTEMPTS):
            try:
                async with self.session.begin():
                    await self.session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
                    return await self._persist(command)
            except DailyBaselineError:
                raise
            except SQLAlchemyError as exc:
                if (
                    _sqlstate(exc) in _RETRYABLE_SQLSTATES
                    and attempt + 1 < _MAX_TRANSACTION_ATTEMPTS
                ):
                    continue
                raise _fail() from exc
        raise _fail()

    async def _persist(
        self, command: PersistDailySnapshotBaselineCommand
    ) -> PersistDailySnapshotBaselineResult:
        if not isinstance(command, PersistDailySnapshotBaselineCommand):
            raise _fail()
        user_id = _text(command.user_id)
        net_worth_id = _text(command.net_worth_snapshot_id)
        granularity = _publication_granularity(command.granularity, command.source)
        publication_job_id = _publication_job_id(
            command.publication_job_id,
            granularity=granularity,
        )
        timestamp = _aligned_publication_timestamp(command.timestamp, granularity)
        created_at = _timestamp(command.created_at)
        currency = _currency(command.currency)
        version = _version(command.calculation_version)
        if not isinstance(command.primary_snapshot_identities, tuple):
            raise _fail()
        await self.session.execute(
            select(func.pg_advisory_xact_lock(_lock_id(f"daily-baseline:{user_id}:{timestamp!s}")))
        )
        user = await self.session.scalar(
            select(UserModel)
            .where(UserModel.id == user_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        net_worth = await self.session.scalar(
            select(NetWorthSnapshotModel)
            .where(NetWorthSnapshotModel.id == net_worth_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if (
            user is None
            or _currency(user.base_currency) != currency
            or net_worth is None
            or net_worth.user_id != user_id
            or net_worth.timestamp != timestamp
            or net_worth.granularity is not granularity
            or net_worth.currency != currency
            or net_worth.calculation_version != version
            or net_worth.source is not command.source
        ):
            raise _fail()

        account_rows = (
            await self.session.scalars(
                select(AccountModel)
                .join(AccountMemberModel, AccountMemberModel.account_id == AccountModel.id)
                .where(
                    AccountMemberModel.user_id == user_id,
                    AccountModel.is_archived.is_(False),
                    AccountModel.archived_at.is_(None),
                )
                .order_by(AccountModel.id)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        ).all()
        accounts = tuple(account_rows)
        account_ids = tuple(account.id for account in accounts)
        if publication_job_id is not None:
            job = await self.session.get(BackgroundJobModel, publication_job_id)
            target = await self.session.get(
                ImportJobPublicationTargetModel,
                (publication_job_id, user_id),
            )
            if (
                job is None
                or target is None
                or target.published_at is not None
                or target.bucket != timestamp
                or job.account_id not in account_ids
                or job.kind is not BackgroundJobKind.import_workflow
                or job.status is BackgroundJobStatus.completed
            ):
                raise _fail()
        identities = command.primary_snapshot_identities
        if (
            len(set(account_ids)) != len(account_ids)
            or len(identities) != len(account_ids)
            or tuple(identity.account_id for identity in identities) != account_ids
            or len({identity.snapshot_id for identity in identities}) != len(identities)
        ):
            raise _fail()

        manifest_accounts: list[DailyBaselineAccount] = []
        for account, identity in zip(accounts, identities, strict=True):
            if not isinstance(identity, SelectedAccountSnapshotIdentity):
                raise _fail()
            primary = await self.session.get(AccountSnapshotModel, _text(identity.snapshot_id))
            if (
                primary is None
                or primary.account_id != account.id
                or primary.timestamp != timestamp
                or primary.granularity is not granularity
                or primary.currency != currency
                or primary.calculation_version != version
                or primary.source is not command.source
            ):
                raise _fail()
            presentation = primary
            account_currency = _currency(account.currency)
            if account_currency != currency:
                presentation_candidate = await self.session.scalar(
                    select(AccountSnapshotModel).where(
                        AccountSnapshotModel.account_id == account.id,
                        AccountSnapshotModel.timestamp == timestamp,
                        AccountSnapshotModel.granularity == granularity,
                        AccountSnapshotModel.currency == account_currency,
                    )
                )
                if (
                    presentation_candidate is None
                    or presentation_candidate.id == primary.id
                    or presentation_candidate.source is not command.source
                    or presentation_candidate.calculation_version != version
                ):
                    raise _fail()
                presentation = presentation_candidate
            elif presentation.id != primary.id:
                raise _fail()
            primary_boundary = await self.session.get(
                AccountSnapshotCanonicalBoundaryModel, primary.id
            )
            presentation_boundary = await self.session.get(
                AccountSnapshotCanonicalBoundaryModel, presentation.id
            )
            if primary_boundary is None or presentation_boundary is None:
                raise _fail()
            item = _boundary_account(
                account=account,
                primary=primary,
                presentation=presentation,
                primary_boundary=primary_boundary,
                presentation_boundary=presentation_boundary,
                granularity=granularity,
            )
            state = await self.session.get(AccountCanonicalStateModel, account.id)
            if (
                state is None
                or state.last_revision < item.canonical_revision
                or state.last_investment_revision
                < (item.investment_revision if item.investment_revision is not None else 0)
            ):
                raise _fail()
            if item.selected_liability_balance_id is not None:
                liability = await self.session.get(
                    LiabilityBalanceModel, item.selected_liability_balance_id
                )
                liability_change = await self.session.scalar(
                    select(AccountCanonicalChangeModel).where(
                        AccountCanonicalChangeModel.kind == "liability_balance",
                        AccountCanonicalChangeModel.entity_id == item.selected_liability_balance_id,
                    )
                )
                if (
                    liability is None
                    or liability.account_id != account.id
                    or liability.effective_at > timestamp
                    or liability_change is None
                    or liability_change.account_id != account.id
                    or liability_change.revision > item.canonical_revision
                    or liability_change.financial_timestamp != liability.effective_at
                    or liability_change.created_at != liability.created_at
                ):
                    raise _fail()
            manifest_accounts.append(item)

        await _validate_net_worth_graph(
            self.session,
            net_worth=net_worth,
            identities=identities,
        )

        baseline_id = _baseline_id(net_worth_id)
        existing = await self.session.get(DailySnapshotBaselineModel, baseline_id)
        if existing is not None:
            children = tuple(
                (
                    await self.session.scalars(
                        select(DailySnapshotBaselineAccountModel)
                        .where(DailySnapshotBaselineAccountModel.baseline_id == baseline_id)
                        .order_by(DailySnapshotBaselineAccountModel.account_id)
                    )
                ).all()
            )
            if not self._matches_persisted(
                existing,
                children,
                user_id=user_id,
                net_worth_id=net_worth_id,
                timestamp=timestamp,
                granularity=granularity,
                publication_job_id=publication_job_id,
                currency=currency,
                version=version,
                source=command.source,
                created_at=created_at,
                accounts=tuple(manifest_accounts),
            ):
                raise _fail()
            return PersistDailySnapshotBaselineResult(
                baseline_id=baseline_id,
                net_worth_snapshot_id=net_worth_id,
                account_count=len(manifest_accounts),
                disposition=DailyBaselineDisposition.replayed,
            )

        conflicting = await self.session.scalar(
            select(DailySnapshotBaselineModel).where(
                DailySnapshotBaselineModel.net_worth_snapshot_id == net_worth_id
            )
        )
        if conflicting is not None:
            raise _fail()
        self.session.add(
            DailySnapshotBaselineModel(
                id=baseline_id,
                user_id=user_id,
                net_worth_snapshot_id=net_worth_id,
                timestamp=timestamp,
                granularity=granularity,
                currency=currency,
                calculation_version=version,
                source=command.source,
                background_job_id=publication_job_id,
                created_at=created_at,
            )
        )
        await self.session.flush()
        self.session.add_all(
            [
                DailySnapshotBaselineAccountModel(
                    baseline_id=baseline_id,
                    account_id=item.account_id,
                    account_type=item.account_type,
                    account_currency=item.account_currency,
                    primary_snapshot_id=item.primary_snapshot_id,
                    presentation_snapshot_id=item.presentation_snapshot_id,
                    canonical_revision=item.canonical_revision,
                    investment_revision=item.investment_revision,
                    holding_revision=item.holding_revision,
                    selected_liability_balance_id=item.selected_liability_balance_id,
                )
                for item in manifest_accounts
            ]
        )
        await self.session.flush()
        return PersistDailySnapshotBaselineResult(
            baseline_id=baseline_id,
            net_worth_snapshot_id=net_worth_id,
            account_count=len(manifest_accounts),
            disposition=DailyBaselineDisposition.created,
        )

    @staticmethod
    def _matches_persisted(
        root: DailySnapshotBaselineModel,
        children: tuple[DailySnapshotBaselineAccountModel, ...],
        *,
        user_id: str,
        net_worth_id: str,
        timestamp: datetime,
        granularity: SnapshotGranularity,
        publication_job_id: str | None,
        currency: str,
        version: int,
        source: SnapshotSource,
        created_at: datetime,
        accounts: tuple[DailyBaselineAccount, ...],
    ) -> bool:
        if (
            root.user_id != user_id
            or root.net_worth_snapshot_id != net_worth_id
            or root.timestamp != timestamp
            or root.granularity is not granularity
            or root.background_job_id != publication_job_id
            or root.currency != currency
            or root.calculation_version != version
            or root.source is not source
            or root.created_at != created_at
            or len(children) != len(accounts)
        ):
            return False
        for persisted, expected in zip(children, accounts, strict=True):
            if any(
                (
                    persisted.account_id != expected.account_id,
                    persisted.account_type is not expected.account_type,
                    persisted.account_currency != expected.account_currency,
                    persisted.primary_snapshot_id != expected.primary_snapshot_id,
                    persisted.presentation_snapshot_id != expected.presentation_snapshot_id,
                    persisted.canonical_revision != expected.canonical_revision,
                    persisted.investment_revision != expected.investment_revision,
                    persisted.holding_revision != expected.holding_revision,
                    persisted.selected_liability_balance_id
                    != expected.selected_liability_balance_id,
                )
            ):
                return False
        return True

    async def select_latest_valid(
        self,
        *,
        user_id: str,
        through: datetime,
        frozen_account_ids: tuple[str, ...] = (),
    ) -> DailySnapshotBaseline:
        if self.session.in_transaction():
            raise DailyBaselineUnavailableError()
        canonical_user = _text(user_id)
        canonical_through = _timestamp(through)
        try:
            async with self.session.begin():
                await self.session.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                )
                root = await self.session.scalar(
                    _published_baseline_query(
                        user_id=canonical_user,
                        through=canonical_through,
                    )
                )
                if root is None:
                    raise DailyBaselineUnavailableError()
                return await self._validate_selected(
                    root,
                    through=canonical_through,
                    frozen_account_ids=frozen_account_ids,
                )
        except DailyBaselineUnavailableError:
            raise
        except (DailyBaselineError, SQLAlchemyError) as exc:
            raise DailyBaselineUnavailableError() from exc

    async def validate_exact_in_transaction(
        self,
        *,
        baseline_id: str,
        user_id: str,
        through: datetime,
        frozen_account_ids: tuple[str, ...] = (),
    ) -> DailySnapshotBaseline:
        """Revalidate the newest exact baseline inside a caller-owned stable read."""

        if not self.session.in_transaction():
            raise DailyBaselineUnavailableError()
        canonical_baseline_id = _text(baseline_id)
        canonical_user = _text(user_id)
        canonical_through = _timestamp(through)
        isolation = await self.session.scalar(text("SHOW transaction_isolation"))
        read_only = await self.session.scalar(text("SHOW transaction_read_only"))
        if (
            not isinstance(isolation, str)
            or isolation.replace("_", " ").lower() not in {"repeatable read", "serializable"}
            or read_only != "on"
        ):
            raise DailyBaselineUnavailableError()
        newest = await self.session.scalar(
            _published_baseline_query(
                user_id=canonical_user,
                through=canonical_through,
            )
        )
        if newest is None or newest.id != canonical_baseline_id:
            raise DailyBaselineUnavailableError()
        try:
            return await self._validate_selected(
                newest,
                through=canonical_through,
                frozen_account_ids=frozen_account_ids,
            )
        except DailyBaselineError as exc:
            raise DailyBaselineUnavailableError() from exc

    async def _validate_selected(
        self,
        root: DailySnapshotBaselineModel,
        *,
        through: datetime,
        frozen_account_ids: tuple[str, ...] = (),
    ) -> DailySnapshotBaseline:
        frozen_accounts = frozenset(_text(account_id) for account_id in frozen_account_ids)
        user = await self.session.get(UserModel, root.user_id)
        net_worth = await self.session.get(NetWorthSnapshotModel, root.net_worth_snapshot_id)
        # Imported lazily to keep the lineage module independent from the
        # snapshot_refresh package's public re-export initialization.
        from app.modules.snapshot_refresh.version import (
            current_coordinated_snapshot_calculation_version,
        )

        current_version = current_coordinated_snapshot_calculation_version()
        if (
            user is None
            or net_worth is None
            or _publication_granularity(root.granularity, root.source) is not root.granularity
            or _publication_job_id(
                root.background_job_id,
                granularity=root.granularity,
            )
            != root.background_job_id
            or root.timestamp != net_worth.timestamp
            or root.granularity is not net_worth.granularity
            or root.currency != _currency(user.base_currency)
            or root.currency != net_worth.currency
            or root.calculation_version != current_version
            or root.calculation_version != net_worth.calculation_version
            or root.source is not net_worth.source
        ):
            raise _fail()
        current_accounts = tuple(
            (
                await self.session.scalars(
                    select(AccountModel)
                    .join(AccountMemberModel, AccountMemberModel.account_id == AccountModel.id)
                    .where(
                        AccountMemberModel.user_id == root.user_id,
                        AccountModel.is_archived.is_(False),
                        AccountModel.archived_at.is_(None),
                    )
                    .order_by(AccountModel.id)
                )
            ).all()
        )
        if root.background_job_id is not None:
            publication_job = await self.session.get(
                BackgroundJobModel,
                root.background_job_id,
            )
            publication_target = await self.session.get(
                ImportJobPublicationTargetModel,
                (root.background_job_id, root.user_id),
            )
            if (
                publication_job is None
                or publication_target is None
                or publication_target.published_at is None
                or publication_target.bucket != root.timestamp
                or publication_job.kind is not BackgroundJobKind.import_workflow
                or publication_job.status is not BackgroundJobStatus.completed
                or publication_job.account_id not in {account.id for account in current_accounts}
            ):
                raise _fail()
        children = tuple(
            (
                await self.session.scalars(
                    select(DailySnapshotBaselineAccountModel)
                    .where(DailySnapshotBaselineAccountModel.baseline_id == root.id)
                    .order_by(DailySnapshotBaselineAccountModel.account_id)
                )
            ).all()
        )
        if tuple(account.id for account in current_accounts) != tuple(
            child.account_id for child in children
        ):
            raise _fail()
        await _validate_net_worth_graph(
            self.session,
            net_worth=net_worth,
            identities=tuple(
                SelectedAccountSnapshotIdentity(
                    account_id=child.account_id,
                    snapshot_id=child.primary_snapshot_id,
                )
                for child in children
            ),
        )
        accounts: list[DailyBaselineAccount] = []
        changes: list[DailyBaselineChange] = []
        for account, child in zip(current_accounts, children, strict=True):
            primary = await self.session.get(AccountSnapshotModel, child.primary_snapshot_id)
            presentation = await self.session.get(
                AccountSnapshotModel, child.presentation_snapshot_id
            )
            primary_boundary = await self.session.get(
                AccountSnapshotCanonicalBoundaryModel, child.primary_snapshot_id
            )
            presentation_boundary = await self.session.get(
                AccountSnapshotCanonicalBoundaryModel, child.presentation_snapshot_id
            )
            state = await self.session.get(AccountCanonicalStateModel, account.id)
            if (
                primary is None
                or presentation is None
                or primary_boundary is None
                or presentation_boundary is None
                or state is None
                or child.account_type is not account.type
                or child.account_currency != _currency(account.currency)
                or primary.timestamp != root.timestamp
                or presentation.timestamp != root.timestamp
                or primary.granularity is not root.granularity
                or presentation.granularity is not root.granularity
                or primary.currency != root.currency
                or presentation.currency != account.currency
                or primary.calculation_version != root.calculation_version
                or presentation.calculation_version != root.calculation_version
                or primary.source is not root.source
                or presentation.source is not root.source
            ):
                raise _fail()
            expected = _boundary_account(
                account=account,
                primary=primary,
                presentation=presentation,
                primary_boundary=primary_boundary,
                presentation_boundary=presentation_boundary,
                granularity=root.granularity,
            )
            if any(
                (
                    child.canonical_revision != expected.canonical_revision,
                    child.investment_revision != expected.investment_revision,
                    child.holding_revision != expected.holding_revision,
                    child.selected_liability_balance_id != expected.selected_liability_balance_id,
                    state.last_revision < child.canonical_revision,
                )
            ):
                raise _fail()
            all_changes = tuple(
                (
                    await self.session.scalars(
                        select(AccountCanonicalChangeModel)
                        .where(AccountCanonicalChangeModel.account_id == account.id)
                        .order_by(AccountCanonicalChangeModel.revision)
                    )
                ).all()
            )
            if len(all_changes) != state.last_revision or any(
                change.revision != expected_revision
                for expected_revision, change in enumerate(all_changes, start=1)
            ):
                raise _fail()
            last_investment_revision = 0
            selected_liability_revision: int | None = None
            for change in all_changes:
                await self._validate_change_root(account.id, change)
                if change.kind == "investment_event":
                    last_investment_revision = change.revision
                if change.entity_id == child.selected_liability_balance_id:
                    selected_liability_revision = change.revision
            if last_investment_revision != state.last_investment_revision:
                raise _fail()
            investment_at_boundary = max(
                (
                    change.revision
                    for change in all_changes
                    if change.kind == "investment_event"
                    and change.revision <= child.canonical_revision
                ),
                default=0,
            )
            if child.investment_revision is not None and (
                child.investment_revision != investment_at_boundary
            ):
                raise _fail()
            if child.selected_liability_balance_id is not None and (
                selected_liability_revision is None
                or selected_liability_revision > child.canonical_revision
            ):
                raise _fail()
            account_changes = tuple(
                change for change in all_changes if change.revision > child.canonical_revision
            )
            for change in account_changes:
                if change.financial_timestamp <= root.timestamp:
                    if account.id not in frozen_accounts:
                        raise _fail()
                    continue
                if change.financial_timestamp <= through:
                    changes.append(
                        DailyBaselineChange(
                            account_id=account.id,
                            revision=_revision(change.revision, positive=True),
                            kind=_text(change.kind),
                            entity_id=_text(change.entity_id),
                            financial_timestamp=_timestamp(change.financial_timestamp),
                        )
                    )
            accounts.append(expected)
        return freeze_baseline_post_changes(
            DailySnapshotBaseline(
                baseline_id=_text(root.id),
                user_id=_text(root.user_id),
                net_worth_snapshot_id=_text(root.net_worth_snapshot_id),
                timestamp=_timestamp(root.timestamp),
                currency=_currency(root.currency),
                calculation_version=_version(root.calculation_version),
                source=root.source,
                accounts=tuple(accounts),
                post_baseline_changes=tuple(
                    sorted(changes, key=lambda item: (item.account_id, item.revision))
                ),
                granularity=root.granularity,
                publication_job_id=root.background_job_id,
            ),
            account_ids=frozen_account_ids,
        )

    async def _validate_change_root(
        self,
        account_id: str,
        change: AccountCanonicalChangeModel,
    ) -> None:
        _revision(change.revision, positive=True)
        entity_id = _text(change.entity_id)
        financial_timestamp = _timestamp(change.financial_timestamp)
        _timestamp(change.created_at)
        if change.kind == "transaction":
            transaction = await self.session.get(TransactionModel, entity_id)
            valid = (
                transaction is not None
                and transaction.account_id == account_id
                and transaction.date == financial_timestamp
                and transaction.created_at == change.created_at
            )
        elif change.kind == "investment_event":
            event = await self.session.get(InvestmentEventModel, entity_id)
            valid = (
                event is not None
                and event.account_id == account_id
                and event.date == financial_timestamp
                and event.created_at == change.created_at
            )
        elif change.kind == "liability_balance":
            liability = await self.session.get(LiabilityBalanceModel, entity_id)
            valid = (
                liability is not None
                and liability.account_id == account_id
                and liability.effective_at == financial_timestamp
                and liability.created_at == change.created_at
            )
        else:
            valid = False
        if not valid:
            raise _fail()
