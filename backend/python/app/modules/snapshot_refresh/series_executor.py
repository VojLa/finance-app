"""Stage one complete snapshot series and publish it only as one generation.

This coordinator deliberately accepts frozen ``CompleteAccountSnapshotEvidence``.
It never reads holdings, performs provider work, or updates read-model pointers.
Physical staging and pointer publication are injected so the latter can verify the
complete manifest and switch every user pointer in a single transaction.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid5

from app.db.models.common import TIMESTAMP
from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.modules.net_worth.evidence_service import SelectedAccountSnapshotIdentity
from app.modules.snapshots.account_projection import ExpectedAccountSnapshotValuation
from app.modules.snapshots.evidence_service import CompleteAccountSnapshotEvidence
from app.modules.snapshots.persistence_projection import (
    AccountSnapshotPersistenceMetadata,
    AccountSnapshotPersistenceProjectionError,
    ExpectedAccountSnapshotPersistence,
    build_account_snapshot_persistence_projection,
)

_STATE_MESSAGE = "Snapshot series staging or publication could not be completed."
_GENERATION_NAMESPACE = UUID("2b5d69a6-b6a0-581d-9ed0-14e6888f5223")
_POSTGRES_INTEGER_MAX = 2_147_483_647


class SnapshotSeriesExecutionStateError(RuntimeError):
    """Raised when a frozen series is incomplete, inconsistent, or cannot stage."""

    def __init__(self) -> None:
        super().__init__(_STATE_MESSAGE)


class SnapshotSeriesPublicationSupersededError(SnapshotSeriesExecutionStateError):
    """A newer causal publication or retirement owns this user's read model."""


@dataclass(frozen=True, slots=True)
class SnapshotSeriesTarget:
    """The complete account scope and output currency for one affected user."""

    user_id: str
    output_currency: str
    account_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SnapshotSeriesAccountEvidence:
    """One frozen account valuation in either native or user-output currency."""

    account_id: str
    account_currency: str
    evidence: CompleteAccountSnapshotEvidence
    canonical_revision: int
    investment_revision: int | None
    holding_revision: int | None


@dataclass(frozen=True, slots=True)
class SnapshotSeriesAccountManifestEntry:
    """One exact physical projection and its frozen canonical boundary."""

    projection: ExpectedAccountSnapshotPersistence
    canonical_revision: int
    investment_revision: int | None
    holding_revision: int | None
    selected_liability_balance_id: str | None


@dataclass(frozen=True, slots=True)
class SnapshotSeriesPoint:
    """All account evidence required for every affected user at one timestamp."""

    timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    calculation_version: int
    calculated_at: datetime
    created_at: datetime
    is_recalculated: bool
    account_evidence: tuple[SnapshotSeriesAccountEvidence, ...]


@dataclass(frozen=True, slots=True)
class ExecuteSnapshotSeriesCommand:
    """A frozen, one-job series plan; it is not a replay or market-data command."""

    job_id: str
    targets: tuple[SnapshotSeriesTarget, ...]
    points: tuple[SnapshotSeriesPoint, ...]
    causal_at: datetime | None = None
    replace_from: datetime | None = None
    dirty_epoch: int | None = None
    staged_by_job_id: str | None = None
    staged_lease_version: int | None = None
    staged_lease_owner: str | None = None


@dataclass(frozen=True, slots=True)
class StagedAccountSnapshot:
    """The exact account row identity returned by the physical staging adapter."""

    snapshot_id: str
    account_id: str
    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    generation_id: str


@dataclass(frozen=True, slots=True)
class SnapshotSeriesAccountSelection:
    """A generation-local account row selected by a user aggregate."""

    account_id: str
    snapshot_id: str
    currency: str


@dataclass(frozen=True, slots=True)
class StageUserSnapshotSeriesProjectionCommand:
    """All generation-local account inputs required to stage one user point."""

    generation_id: str
    user_id: str
    timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    calculation_version: int
    calculated_at: datetime
    created_at: datetime
    is_recalculated: bool
    output_currency: str
    output_account_snapshots: tuple[SelectedAccountSnapshotIdentity, ...]
    native_account_snapshots: tuple[SnapshotSeriesAccountSelection, ...]
    staged_by_job_id: str | None = None
    staged_lease_version: int | None = None
    staged_lease_owner: str | None = None


@dataclass(frozen=True, slots=True)
class StagedUserSnapshotSeriesProjection:
    """The complete staged aggregate identities for one user and timestamp."""

    generation_id: str
    user_id: str
    timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    calculation_version: int
    calculated_at: datetime
    created_at: datetime
    is_recalculated: bool
    output_currency: str
    output_account_snapshots: tuple[SelectedAccountSnapshotIdentity, ...]
    native_account_snapshots: tuple[SnapshotSeriesAccountSelection, ...]
    portfolio_snapshot_id: str
    net_worth_snapshot_id: str
    baseline_id: str


@dataclass(frozen=True, slots=True)
class SnapshotSeriesPublicationManifest:
    """The in-attempt expected set a publisher must verify exactly before switching.

    The publisher owns one database transaction.  It must reject an absent,
    mismatched, or unexpected generation row before it changes any publication
    pointer.  This manifest is intentionally only safe within the durable job
    attempt which supplied ``job_id``; it is not a crash-recovery manifest.
    """

    job_id: str
    generation_id: str
    causal_at: datetime
    account_snapshots: tuple[SnapshotSeriesAccountManifestEntry, ...]
    user_projections: tuple[StagedUserSnapshotSeriesProjection, ...]
    replace_from: datetime | None = None
    dirty_epoch: int | None = None
    staged_by_job_id: str | None = None
    staged_lease_version: int | None = None
    staged_lease_owner: str | None = None


@dataclass(frozen=True, slots=True)
class ExecuteSnapshotSeriesResult:
    generation_id: str
    account_snapshots: tuple[StagedAccountSnapshot, ...]
    user_projections: tuple[StagedUserSnapshotSeriesProjection, ...]


class SnapshotSeriesAccountStager(Protocol):
    """Persist an exact account projection without publishing a user pointer."""

    async def stage(
        self,
        entry: SnapshotSeriesAccountManifestEntry,
    ) -> StagedAccountSnapshot: ...


class SnapshotSeriesUserProjectionStager(Protocol):
    """Persist portfolio, net-worth, and baseline rows without pointer publication."""

    async def stage(
        self,
        command: StageUserSnapshotSeriesProjectionCommand,
    ) -> StagedUserSnapshotSeriesProjection: ...


class AtomicSnapshotSeriesPublisher(Protocol):
    """Verify a complete staged generation and atomically switch all user pointers."""

    async def publish(self, manifest: SnapshotSeriesPublicationManifest) -> None: ...

    async def retire_user(self, user_id: str, *, job_created_at: datetime) -> None: ...


type AccountProjectionBuilder = Callable[
    [CompleteAccountSnapshotEvidence, AccountSnapshotPersistenceMetadata],
    ExpectedAccountSnapshotPersistence,
]


def _fail() -> SnapshotSeriesExecutionStateError:
    return SnapshotSeriesExecutionStateError()


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\0" in value:
        raise _fail()
    return value


def _currency(value: object) -> str:
    currency = _text(value)
    if (
        len(currency) != 3
        or not currency.isascii()
        or not currency.isalpha()
        or currency != currency.upper()
    ):
        raise _fail()
    return currency


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


def _aligned_timestamp(value: object, granularity: SnapshotGranularity) -> datetime:
    timestamp = _timestamp(value)
    if granularity is SnapshotGranularity.minute:
        aligned = timestamp.second == 0 and timestamp.microsecond == 0
    elif granularity is SnapshotGranularity.hour:
        aligned = timestamp.minute == 0 and timestamp.second == 0 and timestamp.microsecond == 0
    elif granularity is SnapshotGranularity.day:
        aligned = timestamp.time() == datetime.min.time()
    elif granularity is SnapshotGranularity.week:
        aligned = timestamp.weekday() == 0 and timestamp.time() == datetime.min.time()
    elif granularity is SnapshotGranularity.month:
        aligned = timestamp.day == 1 and timestamp.time() == datetime.min.time()
    else:
        raise _fail()
    if not aligned:
        raise _fail()
    return timestamp


def _version(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 < value <= _POSTGRES_INTEGER_MAX
    ):
        raise _fail()
    return value


def _revision(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _fail()
    return value


def generation_id_for_job(job_id: str) -> str:
    """Return the deterministic physical generation identity for one durable job."""

    return f"snapshot-series:{uuid5(_GENERATION_NAMESPACE, _text(job_id))}"


def _canonical_targets(value: object) -> tuple[SnapshotSeriesTarget, ...]:
    if not isinstance(value, tuple) or not value:
        raise _fail()
    targets: list[SnapshotSeriesTarget] = []
    for target in value:
        if not isinstance(target, SnapshotSeriesTarget) or not isinstance(
            target.account_ids, tuple
        ):
            raise _fail()
        account_ids = tuple(_text(account_id) for account_id in target.account_ids)
        if (
            not account_ids
            or account_ids != tuple(sorted(account_ids))
            or len(set(account_ids)) != len(account_ids)
        ):
            raise _fail()
        targets.append(
            SnapshotSeriesTarget(
                user_id=_text(target.user_id),
                output_currency=_currency(target.output_currency),
                account_ids=account_ids,
            )
        )
    result = tuple(targets)
    if tuple(target.user_id for target in result) != tuple(
        sorted(target.user_id for target in result)
    ) or len({target.user_id for target in result}) != len(result):
        raise _fail()
    return result


def _canonical_point(value: object) -> SnapshotSeriesPoint:
    if not isinstance(value, SnapshotSeriesPoint) or not isinstance(value.account_evidence, tuple):
        raise _fail()
    if (
        not isinstance(value.granularity, SnapshotGranularity)
        or not isinstance(value.source, SnapshotSource)
        or not isinstance(value.is_recalculated, bool)
        or value.is_recalculated is not (value.source is SnapshotSource.manual_recalculation)
    ):
        raise _fail()
    return SnapshotSeriesPoint(
        timestamp=_aligned_timestamp(value.timestamp, value.granularity),
        granularity=value.granularity,
        source=value.source,
        calculation_version=_version(value.calculation_version),
        calculated_at=_timestamp(value.calculated_at),
        created_at=_timestamp(value.created_at),
        is_recalculated=value.is_recalculated,
        account_evidence=value.account_evidence,
    )


def _canonical_account_evidence(
    value: object,
    *,
    point: SnapshotSeriesPoint,
) -> SnapshotSeriesAccountEvidence:
    if not isinstance(value, SnapshotSeriesAccountEvidence):
        raise _fail()
    account_id = _text(value.account_id)
    account_currency = _currency(value.account_currency)
    evidence = value.evidence
    if not isinstance(evidence, CompleteAccountSnapshotEvidence):
        raise _fail()
    valuation = evidence.valuation
    if (
        not isinstance(valuation, ExpectedAccountSnapshotValuation)
        or _text(valuation.account_id) != account_id
        or _aligned_timestamp(valuation.timestamp, point.granularity) != point.timestamp
        or valuation.granularity is not point.granularity
        or valuation.source is not point.source
        or _version(valuation.calculation_version) != point.calculation_version
    ):
        raise _fail()
    _currency(valuation.currency)
    canonical_revision = _revision(value.canonical_revision)
    investment_revision = value.investment_revision
    holding_revision = value.holding_revision
    if (investment_revision is None) != (holding_revision is None):
        raise _fail()
    if investment_revision is not None:
        investment_revision = _revision(investment_revision)
        holding_revision = _revision(holding_revision)
        if investment_revision != holding_revision or investment_revision > canonical_revision:
            raise _fail()
    return SnapshotSeriesAccountEvidence(
        account_id=account_id,
        account_currency=account_currency,
        evidence=evidence,
        canonical_revision=canonical_revision,
        investment_revision=investment_revision,
        holding_revision=holding_revision,
    )


def _validate_point_coverage(
    point: SnapshotSeriesPoint,
    *,
    targets: tuple[SnapshotSeriesTarget, ...],
) -> SnapshotSeriesPoint:
    target_account_ids = {account_id for target in targets for account_id in target.account_ids}
    account_currencies: dict[str, str] = {}
    evidence_by_coordinate: dict[tuple[str, str], SnapshotSeriesAccountEvidence] = {}
    for item in point.account_evidence:
        canonical = _canonical_account_evidence(item, point=point)
        currency = canonical.evidence.valuation.currency
        previous_currency = account_currencies.setdefault(
            canonical.account_id, canonical.account_currency
        )
        coordinate = (canonical.account_id, currency)
        if (
            canonical.account_id not in target_account_ids
            or previous_currency != canonical.account_currency
            or coordinate in evidence_by_coordinate
        ):
            raise _fail()
        evidence_by_coordinate[coordinate] = canonical

    required_coordinates = {
        (account_id, target.output_currency)
        for target in targets
        for account_id in target.account_ids
    }
    required_coordinates.update(account_currencies.items())
    if (
        set(account_currencies) != target_account_ids
        or set(evidence_by_coordinate) != required_coordinates
    ):
        raise _fail()
    ordered = tuple(
        evidence_by_coordinate[coordinate] for coordinate in sorted(evidence_by_coordinate)
    )
    if point.account_evidence != ordered:
        raise _fail()
    return SnapshotSeriesPoint(
        timestamp=point.timestamp,
        granularity=point.granularity,
        source=point.source,
        calculation_version=point.calculation_version,
        calculated_at=point.calculated_at,
        created_at=point.created_at,
        is_recalculated=point.is_recalculated,
        account_evidence=ordered,
    )


def _canonical_command(value: object) -> ExecuteSnapshotSeriesCommand:
    if not isinstance(value, ExecuteSnapshotSeriesCommand) or not isinstance(value.points, tuple):
        raise _fail()
    targets = _canonical_targets(value.targets)
    points = tuple(_canonical_point(point) for point in value.points)
    if not points or tuple(point.timestamp for point in points) != tuple(
        sorted(point.timestamp for point in points)
    ):
        raise _fail()
    if len({point.timestamp for point in points}) != len(points):
        raise _fail()
    if (value.replace_from is None) != (value.dirty_epoch is None):
        raise _fail()
    if value.dirty_epoch is not None and _revision(value.dirty_epoch) == 0:
        raise _fail()
    provenance = (value.staged_by_job_id, value.staged_lease_version, value.staged_lease_owner)
    if any(part is not None for part in provenance) and not all(
        part is not None for part in provenance
    ):
        raise _fail()
    if value.staged_by_job_id is not None:
        _text(value.staged_by_job_id)
        _revision(value.staged_lease_version)
        _text(value.staged_lease_owner)
    replace_from = _timestamp(value.replace_from) if value.replace_from is not None else None
    if replace_from is not None and points[0].timestamp < replace_from:
        raise _fail()
    return ExecuteSnapshotSeriesCommand(
        job_id=_text(value.job_id),
        targets=targets,
        points=tuple(_validate_point_coverage(point, targets=targets) for point in points),
        causal_at=_timestamp(value.causal_at or min(point.created_at for point in points)),
        replace_from=replace_from,
        dirty_epoch=value.dirty_epoch,
        staged_by_job_id=value.staged_by_job_id,
        staged_lease_version=value.staged_lease_version,
        staged_lease_owner=value.staged_lease_owner,
    )


def _validate_projection(
    projection: object,
    *,
    evidence: SnapshotSeriesAccountEvidence,
    point: SnapshotSeriesPoint,
    generation_id: str,
) -> ExpectedAccountSnapshotPersistence:
    if not isinstance(projection, ExpectedAccountSnapshotPersistence):
        raise _fail()
    snapshot = projection.snapshot
    valuation = evidence.evidence.valuation
    if (
        _text(snapshot.id) != snapshot.id
        or snapshot.account_id != evidence.account_id
        or snapshot.timestamp != point.timestamp
        or snapshot.granularity is not point.granularity
        or snapshot.source is not point.source
        or snapshot.currency != valuation.currency
        or snapshot.calculation_version != point.calculation_version
        or snapshot.calculated_at != point.calculated_at
        or snapshot.created_at != point.created_at
        or snapshot.is_recalculated is not point.is_recalculated
        or snapshot.generation_id != generation_id
    ):
        raise _fail()
    return projection


def _staged_account_matches(
    staged: object,
    *,
    projection: ExpectedAccountSnapshotPersistence,
    generation_id: str,
) -> StagedAccountSnapshot:
    if not isinstance(staged, StagedAccountSnapshot):
        raise _fail()
    expected = projection.snapshot
    if (
        staged.snapshot_id != expected.id
        or staged.account_id != expected.account_id
        or staged.timestamp != expected.timestamp
        or staged.granularity is not expected.granularity
        or staged.currency != expected.currency
        or staged.generation_id != generation_id
    ):
        raise _fail()
    return staged


def _user_stage_command(
    *,
    target: SnapshotSeriesTarget,
    point: SnapshotSeriesPoint,
    generation_id: str,
    projections: dict[tuple[str, str], ExpectedAccountSnapshotPersistence],
    account_currencies: dict[str, str],
    command: ExecuteSnapshotSeriesCommand,
) -> StageUserSnapshotSeriesProjectionCommand:
    output = tuple(
        SelectedAccountSnapshotIdentity(
            account_id=account_id,
            snapshot_id=projections[(account_id, target.output_currency)].snapshot.id,
        )
        for account_id in target.account_ids
    )
    native = tuple(
        SnapshotSeriesAccountSelection(
            account_id=account_id,
            snapshot_id=projections[(account_id, account_currencies[account_id])].snapshot.id,
            currency=account_currencies[account_id],
        )
        for account_id in target.account_ids
    )
    return StageUserSnapshotSeriesProjectionCommand(
        generation_id=generation_id,
        user_id=target.user_id,
        timestamp=point.timestamp,
        granularity=point.granularity,
        source=point.source,
        calculation_version=point.calculation_version,
        calculated_at=point.calculated_at,
        created_at=point.created_at,
        is_recalculated=point.is_recalculated,
        output_currency=target.output_currency,
        output_account_snapshots=output,
        native_account_snapshots=native,
        staged_by_job_id=command.staged_by_job_id,
        staged_lease_version=command.staged_lease_version,
        staged_lease_owner=command.staged_lease_owner,
    )


def _staged_user_matches(
    staged: object,
    *,
    command: StageUserSnapshotSeriesProjectionCommand,
) -> StagedUserSnapshotSeriesProjection:
    if not isinstance(staged, StagedUserSnapshotSeriesProjection):
        raise _fail()
    if (
        staged.generation_id != command.generation_id
        or staged.user_id != command.user_id
        or staged.timestamp != command.timestamp
        or staged.granularity is not command.granularity
        or staged.source is not command.source
        or staged.calculation_version != command.calculation_version
        or staged.calculated_at != command.calculated_at
        or staged.created_at != command.created_at
        or staged.is_recalculated is not command.is_recalculated
        or staged.output_currency != command.output_currency
        or staged.output_account_snapshots != command.output_account_snapshots
        or staged.native_account_snapshots != command.native_account_snapshots
        or any(
            _text(value) != value
            for value in (
                staged.portfolio_snapshot_id,
                staged.net_worth_snapshot_id,
                staged.baseline_id,
            )
        )
    ):
        raise _fail()
    return staged


class SnapshotSeriesExecutor:
    """Build the complete expected manifest before a single publication call.

    Stagers may commit immutable rows independently.  A failed stage therefore
    can leave disposable rows, but cannot move a public pointer: ``publisher``
    is invoked only after every account and every user point has staged and the
    in-memory manifest is complete.
    """

    def __init__(
        self,
        *,
        account_stager: SnapshotSeriesAccountStager,
        user_projection_stager: SnapshotSeriesUserProjectionStager,
        publisher: AtomicSnapshotSeriesPublisher,
        projection_builder: AccountProjectionBuilder = build_account_snapshot_persistence_projection,
    ) -> None:
        self.account_stager = account_stager
        self.user_projection_stager = user_projection_stager
        self.publisher = publisher
        self.projection_builder = projection_builder

    async def execute(
        self,
        command: ExecuteSnapshotSeriesCommand,
    ) -> ExecuteSnapshotSeriesResult:
        canonical = _canonical_command(command)
        generation_id = generation_id_for_job(canonical.job_id)
        receipt_probe = getattr(self.publisher, "has_receipt", None)
        if receipt_probe is not None and await receipt_probe(
            operation_id=canonical.staged_by_job_id or canonical.job_id,
            generation_id=generation_id,
            user_ids=tuple(target.user_id for target in canonical.targets),
        ):
            return ExecuteSnapshotSeriesResult(
                generation_id=generation_id,
                account_snapshots=(),
                user_projections=(),
            )
        projections: list[SnapshotSeriesAccountManifestEntry] = []
        staged_accounts: list[StagedAccountSnapshot] = []
        staged_account_ids: set[str] = set()
        point_projections: dict[
            datetime,
            dict[tuple[str, str], ExpectedAccountSnapshotPersistence],
        ] = {}
        point_account_currencies: dict[datetime, dict[str, str]] = {}

        for point in canonical.points:
            by_coordinate: dict[tuple[str, str], ExpectedAccountSnapshotPersistence] = {}
            account_currencies: dict[str, str] = {}
            for item in point.account_evidence:
                try:
                    projection = self.projection_builder(
                        item.evidence,
                        AccountSnapshotPersistenceMetadata(
                            calculated_at=point.calculated_at,
                            created_at=point.created_at,
                            is_recalculated=point.is_recalculated,
                            generation_id=generation_id,
                        ),
                    )
                except AccountSnapshotPersistenceProjectionError as exc:
                    raise _fail() from exc
                projection = _validate_projection(
                    projection,
                    evidence=item,
                    point=point,
                    generation_id=generation_id,
                )
                coordinate = (item.account_id, projection.snapshot.currency)
                if coordinate in by_coordinate:
                    raise _fail()
                account_currencies[item.account_id] = item.account_currency
                by_coordinate[coordinate] = projection
                manifest_entry = SnapshotSeriesAccountManifestEntry(
                    projection=projection,
                    canonical_revision=item.canonical_revision,
                    investment_revision=item.investment_revision,
                    holding_revision=item.holding_revision,
                    selected_liability_balance_id=(item.evidence.selected_liability_balance_id),
                )
                projections.append(manifest_entry)
                try:
                    staged_account = await self.account_stager.stage(manifest_entry)
                except Exception as exc:
                    raise _fail() from exc
                staged_account = _staged_account_matches(
                    staged_account,
                    projection=projection,
                    generation_id=generation_id,
                )
                if staged_account.snapshot_id in staged_account_ids:
                    raise _fail()
                staged_account_ids.add(staged_account.snapshot_id)
                staged_accounts.append(staged_account)
            point_projections[point.timestamp] = by_coordinate
            point_account_currencies[point.timestamp] = account_currencies

        staged_users: list[StagedUserSnapshotSeriesProjection] = []
        for point in canonical.points:
            for target in canonical.targets:
                stage_command = _user_stage_command(
                    target=target,
                    point=point,
                    generation_id=generation_id,
                    projections=point_projections[point.timestamp],
                    account_currencies=point_account_currencies[point.timestamp],
                    command=canonical,
                )
                try:
                    staged_user = await self.user_projection_stager.stage(stage_command)
                except Exception as exc:
                    raise _fail() from exc
                staged_users.append(_staged_user_matches(staged_user, command=stage_command))

        causal_at = canonical.causal_at
        if causal_at is None:  # Canonicalization always supplies this value.
            raise _fail()

        manifest = SnapshotSeriesPublicationManifest(
            job_id=canonical.job_id,
            generation_id=generation_id,
            causal_at=causal_at,
            account_snapshots=tuple(projections),
            user_projections=tuple(staged_users),
            replace_from=canonical.replace_from,
            dirty_epoch=canonical.dirty_epoch,
            staged_by_job_id=canonical.staged_by_job_id,
            staged_lease_version=canonical.staged_lease_version,
            staged_lease_owner=canonical.staged_lease_owner,
        )
        try:
            await self.publisher.publish(manifest)
        except SnapshotSeriesPublicationSupersededError:
            raise
        except Exception as exc:
            raise _fail() from exc
        return ExecuteSnapshotSeriesResult(
            generation_id=generation_id,
            account_snapshots=tuple(staged_accounts),
            user_projections=tuple(staged_users),
        )

    async def retire_user(self, user_id: str, *, job_created_at: datetime) -> None:
        """Make an empty canonical scope invisible without deleting audit evidence."""

        try:
            await self.publisher.retire_user(
                _text(user_id),
                job_created_at=_timestamp(job_created_at),
            )
        except Exception as exc:
            raise _fail() from exc
