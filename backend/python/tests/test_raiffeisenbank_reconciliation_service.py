from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.db.models.enums import (
    AccountRelationType,
    AccountType,
    ImportRowStatus,
    ImportSource,
)
from app.modules.imports.classification import TransactionPostingIntent, classify_import_row
from app.modules.imports.parsers import parse_import_file
from app.modules.imports.raiffeisenbank import normalize_raiffeisenbank_import_row
from app.modules.imports.raiffeisenbank_reconciliation import plan_raiffeisenbank_reconciliation
from app.modules.imports.raiffeisenbank_reconciliation_repository import (
    RaiffeisenbankReconciliationEvidenceRow,
)
from app.modules.imports.raiffeisenbank_reconciliation_service import (
    RaiffeisenbankReconciliationService,
    RaiffeisenbankReconciliationStateError,
    ReconcileRaiffeisenbankJobCommand,
    _candidates,
    _reconciliation_accounts,
)

_FIXTURES = Path(__file__).parents[3] / "test_imports" / "RB"
_NOW = datetime(2026, 8, 20, 12, 0, 0)


class _Session:
    def __init__(self) -> None:
        self.commits = self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _Repository:
    def __init__(self, *, current_job, evidence, accounts, members, pairs=()) -> None:
        self.current_job = current_job
        self.evidence = evidence
        self.accounts = accounts
        self.members = members
        self.pairs = list(pairs)
        self.created_pairs: list[Any] = []
        self.affected: list[Any] = []

    async def load_current_and_completed_evidence_for_update(self, **_: object):
        return self.current_job, self.evidence

    async def lock_accounts_and_members(self, **_: object):
        return self.accounts, self.members

    async def load_occurrences_for_update(self, **_: object):
        return ()

    async def load_pairs_for_update(self, **_: object):
        return tuple(self.pairs)

    async def get_affected_account_for_update(self, *, job_id: str, account_id: str):
        return next(
            (
                value
                for value in self.affected
                if value.job_id == job_id and value.account_id == account_id
            ),
            None,
        )

    def add_pair(self, value) -> None:
        self.created_pairs.append(value)

    def add_affected_account(self, value) -> None:
        self.affected.append(value)

    async def flush(self) -> None:
        return None


def _pair_evidence():
    basic = parse_import_file(
        ImportSource.raiffeisenbank, (_FIXTURES / "Basic CZK.csv").read_bytes(), encoding=None
    )
    savings = parse_import_file(
        ImportSource.raiffeisenbank, (_FIXTURES / "Savings.csv").read_bytes(), encoding=None
    )
    basic_by_id = {row.raw_data.get("Id transakce"): row for row in basic}
    for savings_row in savings:
        shared_id = savings_row.raw_data.get("Id transakce")
        if shared_id and shared_id in basic_by_id:
            return _evidence_row(
                job_id="prior-basic",
                batch_id="basic-batch",
                account_id="basic",
                transaction_id="basic-transaction",
                raw_data=basic_by_id[shared_id].raw_data,
                row_number=1,
            ), _evidence_row(
                job_id="current-savings",
                batch_id="savings-batch",
                account_id="savings",
                transaction_id="savings-transaction",
                raw_data=savings_row.raw_data,
                row_number=1,
            )
    raise AssertionError("Expected a reciprocal Basic/Savings fixture row.")


def _evidence_row(*, job_id, batch_id, account_id, transaction_id, raw_data, row_number):
    normalized = normalize_raiffeisenbank_import_row(account_id=account_id, raw_data=raw_data)
    assert normalized.data is not None
    intent = classify_import_row(
        source=ImportSource.raiffeisenbank, normalized_data=normalized.data
    )
    assert isinstance(intent, TransactionPostingIntent)
    batch = SimpleNamespace(id=batch_id, account_id=account_id)
    row = SimpleNamespace(
        id=f"{batch_id}-{row_number}",
        import_batch_id=batch_id,
        raw_data=raw_data,
        normalized_data=normalized.data,
        status=ImportRowStatus.imported,
    )
    transaction = SimpleNamespace(
        id=transaction_id,
        import_batch_id=batch_id,
        account_id=account_id,
        date=datetime.fromisoformat(intent.date),
        amount=intent.amount,
        currency=intent.currency,
        type=intent.transaction_type,
        classification=intent.transaction_classification,
        external_id=normalized.data["external_id"],
    )
    return RaiffeisenbankReconciliationEvidenceRow(
        job=cast(Any, SimpleNamespace(id=job_id)),
        batch=cast(Any, batch),
        row=cast(Any, row),
        transaction=cast(Any, transaction),
    )


def _accounts_and_members():
    accounts = (
        SimpleNamespace(id="basic", type=AccountType.bank, currency="CZK"),
        SimpleNamespace(id="savings", type=AccountType.savings, currency="CZK"),
    )
    members = tuple(
        SimpleNamespace(
            account_id=account.id, user_id="owner", relation_type=AccountRelationType.owner
        )
        for account in accounts
    )
    return accounts, members


@pytest.mark.asyncio
async def test_late_arrival_creates_only_current_anchored_pair_and_affected_union() -> None:
    prior, current = _pair_evidence()
    accounts, members = _accounts_and_members()
    session = _Session()
    repository = _Repository(
        current_job=SimpleNamespace(id="current-savings", account_id="savings"),
        evidence=(prior, current),
        accounts=accounts,
        members=members,
    )
    service = RaiffeisenbankReconciliationService(session)  # type: ignore[arg-type]
    service.repository = repository

    result = await service.reconcile(
        command=ReconcileRaiffeisenbankJobCommand(
            job_id="current-savings", user_id="owner", created_at=_NOW
        )
    )

    assert result.pairs_created == 1
    assert result.pairs_replayed == 0
    assert len(repository.created_pairs) == 1
    assert repository.created_pairs[0].background_job_id == "current-savings"
    assert repository.created_pairs[0].published_at is None
    assert result.affected_account_ids == ("basic", "savings")
    assert {value.account_id for value in repository.affected} == {"basic", "savings"}
    assert session.commits == 1


@pytest.mark.asyncio
async def test_unpublished_pair_owned_by_another_job_fails_closed() -> None:
    prior, current = _pair_evidence()
    accounts, members = _accounts_and_members()
    evidence = (prior, current)
    reconciliation_accounts = _reconciliation_accounts(
        accounts=accounts,
        members=members,
        account_ids=("basic", "savings"),
        user_id="owner",
    )
    plan = plan_raiffeisenbank_reconciliation(
        accounts=reconciliation_accounts,
        candidates=_candidates(
            # The service's internal unique-evidence output has identical shape.
            tuple(
                SimpleNamespace(batch=value.batch, row=value.row, transaction=value.transaction)
                for value in evidence
            )
        ),
    )
    pair = plan.pairs[0]
    existing = SimpleNamespace(
        id=pair.pair_id,
        from_transaction_id=pair.from_transaction_id,
        to_transaction_id=pair.to_transaction_id,
        classification=pair.classification,
        source=ImportSource.raiffeisenbank,
        evidence_version=1,
        evidence_hash=pair.evidence_hash,
        background_job_id="other-running-job",
        published_at=None,
    )
    session = _Session()
    repository = _Repository(
        current_job=SimpleNamespace(id="current-savings", account_id="savings"),
        evidence=evidence,
        accounts=accounts,
        members=members,
        pairs=(existing,),
    )
    service = RaiffeisenbankReconciliationService(session)  # type: ignore[arg-type]
    service.repository = repository

    with pytest.raises(RaiffeisenbankReconciliationStateError):
        await service.reconcile(
            command=ReconcileRaiffeisenbankJobCommand(
                job_id="current-savings", user_id="owner", created_at=_NOW
            )
        )
    assert not repository.created_pairs
    assert session.commits == 0
    assert session.rollbacks == 1
