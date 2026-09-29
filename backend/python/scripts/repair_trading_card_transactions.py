"""Repair misclassified Trading 212 Card cash movements for one exact account.

The repair is deliberately narrow: it accepts only the ten known import rows,
rebuilds their current canonical row data from the preserved provider payload,
and uses the normal transaction posting writer so a new canonical revision is
allocated for every replacement cash movement.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.common import TIMESTAMP
from app.db.models.enums import (
    ImportRowStatus,
    ImportSource,
    ImportStatus,
    InvestmentEventType,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.ledger import InvestmentEventModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.canonical_state import CanonicalChangeKind, CanonicalStateService
from app.modules.imports.classification import PostingIntentTarget, classify_import_row
from app.modules.imports.posting_common import (
    DEDUPLICATION_METADATA_KEY,
    POSTING_INTENT_METADATA_KEY,
    UNIQUE_DEDUPLICATION_MARKER,
)
from app.modules.imports.trading212 import normalize_trading212_import_row
from app.modules.imports.transaction_posting import (
    ImportTransactionPostingWriter,
    build_transaction_posting_plan,
)
from app.modules.market_data.source_policy import market_evidence_source_policy_from_settings
from app.modules.portfolio_history.invalidation.service import (
    PortfolioHistoryInvalidationService,
)
from app.modules.snapshot_refresh.executor import (
    ExecuteUserSnapshotRefreshCommand,
    UserSnapshotRefreshExecutor,
)

_CARD_ACTIONS = frozenset({"card debit", "new card cost"})
_CASHBACK_ACTION = "spending cashback"


@dataclass(frozen=True, slots=True)
class _TargetRow:
    row: ImportRowModel
    batch: ImportBatchModel
    action: str


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument(
        "--publish-at",
        help="Also publish a manual daily snapshot at a naive midnight ISO timestamp.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the repair. Without this flag, the script only validates its exact scope.",
    )
    return parser


def _action(row: ImportRowModel) -> str | None:
    raw = row.raw_data
    value = raw.get("Action") if isinstance(raw, dict) else None
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().casefold().split())
    return normalized or None


def _timestamp() -> datetime:
    precision = TIMESTAMP.precision
    if precision is None or not 0 <= precision <= 6:
        raise RuntimeError("Canonical TIMESTAMP precision is unavailable.")
    now = datetime.now(UTC).replace(tzinfo=None)
    unit = 10 ** (6 - precision)
    return now.replace(microsecond=now.microsecond - (now.microsecond % unit))


def _history_timestamp() -> datetime:
    now = _timestamp()
    return now.replace(microsecond=now.microsecond - (now.microsecond % 1_000))


def _writer_batch(batch: ImportBatchModel) -> ImportBatchModel:
    """Give the closed writer its required processing-state view without persisting it."""
    return ImportBatchModel(
        id=batch.id,
        user_id=batch.user_id,
        account_id=batch.account_id,
        source=batch.source,
        filename=batch.filename,
        file_size=batch.file_size,
        file_encoding=batch.file_encoding,
        checksum=batch.checksum,
        status=ImportStatus.processing,
        rows_total=batch.rows_total,
        rows_imported=batch.rows_imported,
        rows_skipped=batch.rows_skipped,
        created_at=batch.created_at,
        completed_at=None,
        retain_until=batch.retain_until,
        raw_data_purged_at=batch.raw_data_purged_at,
    )


def _replacement_data(*, account_id: str, row: ImportRowModel) -> dict[str, object]:
    normalized = normalize_trading212_import_row(account_id=account_id, raw_data=row.raw_data)
    if (
        normalized.data is None
        or normalized.deduplication_key is None
        or normalized.validation_errors
    ):
        raise RuntimeError(f"Trading Card row {row.id} can no longer be normalized safely.")
    intent = classify_import_row(
        source=ImportSource.trading212,
        normalized_data=normalized.data,
    ).model_dump(mode="json")
    if intent.get("target") != PostingIntentTarget.transaction.value:
        raise RuntimeError(f"Trading Card row {row.id} does not classify as a transaction.")
    return {
        **normalized.data,
        DEDUPLICATION_METADATA_KEY: UNIQUE_DEDUPLICATION_MARKER,
        POSTING_INTENT_METADATA_KEY: intent,
    }


async def _load_targets(
    session: AsyncSession, *, email: str, account_id: str
) -> tuple[list[_TargetRow], int, int]:
    account = await session.scalar(
        select(AccountModel)
        .join(AccountMemberModel, AccountMemberModel.account_id == AccountModel.id)
        .join(UserModel, UserModel.id == AccountMemberModel.user_id)
        .where(AccountModel.id == account_id, UserModel.email.ilike(email))
        .with_for_update()
    )
    if account is None:
        raise RuntimeError("The requested user does not have the requested account.")
    rows = (
        await session.execute(
            select(ImportRowModel, ImportBatchModel)
            .join(ImportBatchModel, ImportBatchModel.id == ImportRowModel.import_batch_id)
            .where(
                ImportBatchModel.account_id == account.id,
                ImportBatchModel.source == ImportSource.trading212,
            )
            .with_for_update()
            .order_by(ImportBatchModel.id, ImportRowModel.row_number)
        )
    ).all()
    targets = [
        _TargetRow(row=row, batch=batch, action=action)
        for row, batch in rows
        if (action := _action(row)) in (_CARD_ACTIONS | {_CASHBACK_ACTION})
    ]
    card_count = sum(target.action in _CARD_ACTIONS for target in targets)
    cashback_count = sum(target.action == _CASHBACK_ACTION for target in targets)
    if card_count != 7 or cashback_count != 4:
        raise RuntimeError(
            f"Expected exactly seven card debits/costs and four cashbacks; found "
            f"{card_count} and {cashback_count}."
        )
    return targets, card_count, cashback_count


async def _repair(
    session: AsyncSession,
    *,
    email: str,
    account_id: str,
    settings: Settings,
) -> tuple[int, int, int, int, int]:
    targets, card_count, cashback_count = await _load_targets(
        session, email=email, account_id=account_id
    )
    replacements = 0
    canonical_state = CanonicalStateService(session)
    writer = ImportTransactionPostingWriter(session, canonical_state=canonical_state)
    changes = []
    for target in targets:
        row, batch = target.row, target.batch
        replacement = _replacement_data(account_id=account_id, row=row)
        row.normalized_data = replacement
        row.deduplication_key = normalize_trading212_import_row(
            account_id=account_id, raw_data=row.raw_data
        ).deduplication_key
        row.validation_errors = None
        row.error_message = None

        if row.created_transaction_id is not None:
            row.status = ImportRowStatus.imported
            row.created_investment_event_id = None
            build_transaction_posting_plan(
                account_id=account_id, batch=_writer_batch(batch), row=row
            )
            transaction = await session.get(TransactionModel, row.created_transaction_id)
            if transaction is None or transaction.account_id != account_id:
                raise RuntimeError(
                    f"Trading Card row {row.id} has an invalid replacement transaction."
                )
            # The writer's replay branch validates the complete canonical transaction
            # shape and the durable canonical revision before accepting idempotence.
            transaction = await writer.post_row(
                account_id=account_id, batch=_writer_batch(batch), row=row
            )
            changes.append(
                await canonical_state.record(
                    account_id=account_id,
                    kind=CanonicalChangeKind.transaction,
                    entity_id=transaction.id,
                    financial_timestamp=transaction.date,
                    created_at=transaction.created_at,
                    replay=True,
                )
            )
            continue

        if target.action in _CARD_ACTIONS:
            if (
                row.status is not ImportRowStatus.needs_review
                or row.created_investment_event_id is not None
            ):
                raise RuntimeError(
                    f"Card row {row.id} is not the expected review-only legacy shape."
                )
        else:
            if row.status is not ImportRowStatus.imported or not row.created_investment_event_id:
                raise RuntimeError(
                    f"Cashback row {row.id} is not the expected legacy investment shape."
                )
            event = await session.get(
                InvestmentEventModel, row.created_investment_event_id, with_for_update=True
            )
            if (
                event is None
                or event.account_id != account_id
                or event.source is not ImportSource.trading212
                or event.type is not InvestmentEventType.interest
                or event.deleted_at is not None
            ):
                raise RuntimeError(
                    f"Cashback row {row.id} is not a live Trading212 interest event."
                )
            # Confirm the legacy event retains its own durable revision before it is
            # retired. The replacement transaction receives a new revision below.
            changes.append(
                await canonical_state.record(
                    account_id=account_id,
                    kind=CanonicalChangeKind.investment_event,
                    entity_id=event.id,
                    financial_timestamp=event.date,
                    created_at=event.created_at,
                    replay=True,
                )
            )
            event.deleted_at = _timestamp()
            event.updated_at = event.deleted_at

        row.status = ImportRowStatus.pending
        row.created_transaction_id = None
        row.created_investment_event_id = None
        transaction = await writer.post_row(
            account_id=account_id, batch=_writer_batch(batch), row=row
        )
        changes.append(
            await canonical_state.record(
                account_id=account_id,
                kind=CanonicalChangeKind.transaction,
                entity_id=transaction.id,
                financial_timestamp=transaction.date,
                created_at=transaction.created_at,
                replay=True,
            )
        )
        replacements += 1
    cashback_ids = {
        target.row.raw_data.get("ID") for target in targets if target.action == _CASHBACK_ACTION
    }
    if len(cashback_ids) != 4 or not all(
        isinstance(value, str) and value for value in cashback_ids
    ):
        raise RuntimeError("Cashback source identities are unavailable.")
    retired = (
        await session.scalars(
            select(InvestmentEventModel)
            .where(
                InvestmentEventModel.account_id == account_id,
                InvestmentEventModel.source == ImportSource.trading212,
                InvestmentEventModel.type == InvestmentEventType.interest,
                InvestmentEventModel.external_id.in_(cashback_ids),
                InvestmentEventModel.deleted_at.is_not(None),
            )
            .with_for_update()
        )
    ).all()
    if len(retired) != 4 or {event.external_id for event in retired} != cashback_ids:
        raise RuntimeError("Retired cashback interest events are not the exact expected set.")
    known = {(change.kind, change.entity_id) for change in changes}
    for event in retired:
        identity = (CanonicalChangeKind.investment_event, event.id)
        if identity not in known:
            changes.append(
                await canonical_state.record(
                    account_id=account_id,
                    kind=CanonicalChangeKind.investment_event,
                    entity_id=event.id,
                    financial_timestamp=event.date,
                    created_at=event.created_at,
                    replay=True,
                )
            )
    changes = sorted(changes, key=lambda change: (change.account_id, change.revision))
    if (
        len(changes) != 15
        or len({(change.account_id, change.revision) for change in changes}) != 15
    ):
        raise RuntimeError("Trading Card canonical repair effects are incomplete.")
    history = PortfolioHistoryInvalidationService(
        session,
        source_policy=market_evidence_source_policy_from_settings(settings),
    )
    memberships = await history.lock_current_memberships((account_id,))
    invalidation = await history.invalidate_recorded_changes(
        changes=tuple(changes),
        locked_memberships=memberships,
        now=_history_timestamp(),
    )
    return (
        card_count,
        cashback_count,
        replacements,
        invalidation.inserted_receipts,
        invalidation.enqueued_jobs,
    )


async def _execute(args: argparse.Namespace) -> None:
    settings = Settings()
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is required for the Trading Card repair.")
    engine = create_async_engine(normalize_database_url(settings.database_url))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            if not args.apply:
                targets, card_count, cashback_count = await _load_targets(
                    session, email=args.email, account_id=args.account_id
                )
                await session.rollback()
                print(
                    f"Validated {len(targets)} Trading Card rows: {card_count} debits/costs and "
                    f"{cashback_count} cashbacks. Re-run with --apply to commit."
                )
                return
            async with session.begin():
                card_count, cashback_count, replacements, receipts, jobs = await _repair(
                    session, email=args.email, account_id=args.account_id, settings=settings
                )
            print(
                f"Repaired {replacements} Trading Card row(s): {card_count} debits/costs and "
                f"{cashback_count} cashbacks for account {args.account_id}; history receipts="
                f"{receipts}, jobs={jobs}."
            )
            if args.publish_at:
                publish_at = datetime.fromisoformat(args.publish_at)
                if publish_at.tzinfo is not None or publish_at.time() != datetime.min.time():
                    raise RuntimeError("--publish-at must be a naive midnight ISO timestamp.")
                user_id = await session.scalar(
                    select(UserModel.id).where(UserModel.email.ilike(args.email))
                )
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
