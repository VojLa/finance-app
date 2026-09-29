from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from runpy import run_path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.db.models.enums import ImportRowStatus, ImportSource
from app.db.models.imports import ImportRowModel
from app.modules.imports import deduplication as deduplication_module
from app.modules.imports.deduplication import (
    ImportDeduplicateStateError,
    ImportDeduplicationService,
    _card_multiset_normalized_payload,
)
from app.modules.imports.parsers import parse_import_file
from app.modules.imports.raiffeisenbank import normalize_raiffeisenbank_import_row
from app.modules.imports.raiffeisenbank_card_multiset import (
    RaiffeisenbankCardCandidate,
    RaiffeisenbankCardMultisetEvidenceError,
    plan_raiffeisenbank_card_multiset,
    raiffeisenbank_card_full_fingerprint,
)

_EXPORT_BUILDERS = run_path(
    str(Path(__file__).parent / "fixtures" / "raiffeisenbank" / "synthetic_exports.py")
)
_CARD_EXPORTS = cast(Callable[[], dict[str, bytes]], _EXPORT_BUILDERS["card_multiset_exports"])()
ACCOUNT_ID = "rb-credit-card-account"
CandidateMutator = Callable[[RaiffeisenbankCardCandidate], RaiffeisenbankCardCandidate]


def _fixture_candidates(filename: str, batch_id: str) -> list[RaiffeisenbankCardCandidate]:
    rows = parse_import_file(
        ImportSource.raiffeisenbank,
        _CARD_EXPORTS[filename],
        encoding=None,
    )
    candidates: list[RaiffeisenbankCardCandidate] = []
    for row in rows:
        assert row.validation_errors is None
        normalized = normalize_raiffeisenbank_import_row(
            account_id=ACCOUNT_ID,
            raw_data=row.raw_data,
        )
        assert normalized.data is not None
        assert normalized.validation_errors is None
        candidates.append(
            RaiffeisenbankCardCandidate(
                batch_id=batch_id,
                row_id=f"{batch_id}:{row.row_number}",
                row_number=row.row_number,
                raw_data=row.raw_data,
                normalized_data=normalized.data,
            )
        )
    return candidates


@pytest.fixture(scope="module")
def credit_candidates() -> tuple[
    list[RaiffeisenbankCardCandidate], list[RaiffeisenbankCardCandidate]
]:
    return (
        _fixture_candidates("Credit.csv", "credit-current"),
        _fixture_candidates("Credit 2.csv", "credit-history"),
    )


def test_synthetic_credit_exports_plan_the_exact_multiset(
    credit_candidates: tuple[list[RaiffeisenbankCardCandidate], list[RaiffeisenbankCardCandidate]],
) -> None:
    current, history = credit_candidates
    plan = plan_raiffeisenbank_card_multiset(
        account_id=ACCOUNT_ID,
        candidates=[*current, *history],
    )

    assert len(current) + len(history) == 2_000
    assert plan.physical_row_count == 2_000
    assert plan.canonical_row_count == 1_984
    assert len(plan.duplicate_row_ids) == 16
    assert len(set(plan.canonical_row_ids)) == 1_984
    assert not set(plan.canonical_row_ids) & set(plan.duplicate_row_ids)

    by_row_id = {candidate.row_id: candidate for candidate in [*current, *history]}
    duplicate_batches = {by_row_id[row_id].batch_id for row_id in plan.duplicate_row_ids}
    assert duplicate_batches == {"credit-history"}


def test_synthetic_credit_exports_preserve_all_within_file_repetitions(
    credit_candidates: tuple[list[RaiffeisenbankCardCandidate], list[RaiffeisenbankCardCandidate]],
) -> None:
    current, history = credit_candidates
    candidates = [*current, *history]
    plan = plan_raiffeisenbank_card_multiset(account_id=ACCOUNT_ID, candidates=candidates)
    row_ids_by_batch_fingerprint: dict[tuple[str, str], list[str]] = {}
    for candidate in candidates:
        fingerprint = raiffeisenbank_card_full_fingerprint(raw_data=candidate.raw_data)
        row_ids_by_batch_fingerprint.setdefault((candidate.batch_id, fingerprint), []).append(
            candidate.row_id
        )

    legitimate_repeat_ids = {
        row_id
        for row_ids in row_ids_by_batch_fingerprint.values()
        for row_id in sorted(row_ids)[1:]
    }
    by_row_id = {candidate.row_id: candidate for candidate in candidates}
    total = sum(
        (-Decimal(str(by_row_id[row_id].normalized_data["amount"])))
        for row_id in legitimate_repeat_ids
    )

    assert len(legitimate_repeat_ids) == 36
    assert total == Decimal("1751")
    assert legitimate_repeat_ids <= set(plan.canonical_row_ids)
    assert not legitimate_repeat_ids & set(plan.duplicate_row_ids)


def test_synthetic_credit_plan_is_independent_of_row_and_file_order(
    credit_candidates: tuple[list[RaiffeisenbankCardCandidate], list[RaiffeisenbankCardCandidate]],
) -> None:
    current, history = credit_candidates
    ordered = plan_raiffeisenbank_card_multiset(
        account_id=ACCOUNT_ID,
        candidates=[*current, *history],
    )
    reversed_rows_and_files = plan_raiffeisenbank_card_multiset(
        account_id=ACCOUNT_ID,
        candidates=[*reversed(history), *reversed(current)],
    )

    assert reversed_rows_and_files == ordered
    assert [occurrence.deduplication_key for occurrence in ordered.occurrences] == [
        occurrence.deduplication_key for occurrence in reversed_rows_and_files.occurrences
    ]


def test_occurrence_key_excludes_row_number_but_representative_uses_it() -> None:
    base = _fixture_candidates("Credit.csv", "only-batch")[0]
    later = replace(base, row_id="later", row_number=20)
    earlier = replace(base, row_id="earlier", row_number=10)
    later_plan = plan_raiffeisenbank_card_multiset(account_id=ACCOUNT_ID, candidates=[later])
    earlier_plan = plan_raiffeisenbank_card_multiset(account_id=ACCOUNT_ID, candidates=[earlier])

    assert (
        later_plan.occurrences[0].deduplication_key == earlier_plan.occurrences[0].deduplication_key
    )
    assert later_plan.occurrences[0].canonical_row_number == 20
    assert earlier_plan.occurrences[0].canonical_row_number == 10


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda candidate: replace(
                candidate,
                normalized_data={**candidate.normalized_data, "amount": "999"},
            ),
            id="conflicting-normalized-evidence",
        ),
        pytest.param(
            lambda candidate: replace(
                candidate,
                raw_data={
                    **candidate.raw_data,
                    "__raiffeisenbank_statement_kind": "account_statement",
                },
            ),
            id="wrong-statement-kind",
        ),
        pytest.param(
            lambda candidate: replace(
                candidate,
                raw_data={
                    key: value
                    for key, value in candidate.raw_data.items()
                    if key != "Měna zaúčtování"
                },
            ),
            id="corrupt-missing-currency",
        ),
    ],
)
def test_conflicting_or_corrupt_card_evidence_fails_closed(mutate: CandidateMutator) -> None:
    original = _fixture_candidates("Credit.csv", "credit")[0]
    malformed = mutate(original)

    with pytest.raises(RaiffeisenbankCardMultisetEvidenceError):
        plan_raiffeisenbank_card_multiset(account_id=ACCOUNT_ID, candidates=[malformed])


def test_cross_batch_multiplicity_uses_maximum_not_sum() -> None:
    original = _fixture_candidates("Credit.csv", "batch-a")[0]
    batch_a = [replace(original, row_id=f"a-{index}", row_number=index) for index in range(1, 4)]
    batch_b = [
        replace(original, batch_id="batch-b", row_id=f"b-{index}", row_number=index)
        for index in range(1, 3)
    ]

    plan = plan_raiffeisenbank_card_multiset(account_id=ACCOUNT_ID, candidates=[*batch_b, *batch_a])

    assert plan.physical_row_count == 5
    assert plan.canonical_row_count == 3
    assert len(plan.duplicate_row_ids) == 2
    assert Counter(occurrence.occurrence_ordinal for occurrence in plan.occurrences) == Counter(
        {1: 1, 2: 1, 3: 1}
    )


def test_manifest_replay_strips_only_the_exact_deduplication_marker() -> None:
    candidate = _fixture_candidates("Credit.csv", "credit")[0]
    row = SimpleNamespace(
        status=ImportRowStatus.pending,
        normalized_data={
            **candidate.normalized_data,
            "deduplication": {"schema_version": 1, "status": "unique"},
        },
    )

    assert _card_multiset_normalized_payload(cast(ImportRowModel, row)) == candidate.normalized_data
    assert "deduplication" in row.normalized_data


@pytest.mark.parametrize(
    "normalized_data",
    [
        {"deduplication": {"schema_version": 2, "status": "unique"}},
        {"deduplication": {"schema_version": 1, "status": "duplicate"}},
        {"posting_intent": {"schema_version": 1}},
    ],
    ids=("wrong-marker-version", "wrong-marker-status", "posting-intent"),
)
def test_manifest_replay_rejects_corrupt_workflow_metadata(
    normalized_data: dict[str, object],
) -> None:
    candidate = _fixture_candidates("Credit.csv", "credit")[0]
    row = SimpleNamespace(
        status=ImportRowStatus.pending,
        normalized_data={**candidate.normalized_data, **normalized_data},
    )

    with pytest.raises(ImportDeduplicateStateError):
        _card_multiset_normalized_payload(cast(ImportRowModel, row))


@pytest.mark.asyncio
async def test_non_card_raiffeisenbank_manifest_uses_the_normal_deduplication_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class _OccurrenceRepository:
        def __init__(self, _session: object) -> None:
            pass

        async def load_manifested_card_rows_for_update(self, **kwargs: object) -> object:
            calls.append(kwargs)
            return SimpleNamespace(is_credit_card_account=False)

    service: Any = object.__new__(ImportDeduplicationService)
    service.session = object()
    monkeypatch.setattr(
        deduplication_module,
        "RaiffeisenbankCardOccurrenceRepository",
        _OccurrenceRepository,
    )

    assert (
        await service._deduplicate_manifested_raiffeisenbank_cards(
            principal=SimpleNamespace(user_id="owner"),
            account_id="bank-account",
            batch_id="batch",
            job_id="job",
            current_rows=[],
            locked_batch=SimpleNamespace(source=ImportSource.raiffeisenbank),
        )
        is None
    )
    assert calls == [{"job_id": "job", "user_id": "owner", "account_id": "bank-account"}]
