from types import SimpleNamespace
from typing import cast

import pytest

from app.db.models.canonical_lineage import (
    UserReadModelPublicationModel,
    UserReadModelPublicationWatermarkModel,
)
from app.modules.daily_baselines.service import _is_equivalent_superseding_publication
from app.modules.jobs.repository import _matches_live_publication_boundary


def _six_account_boundary() -> dict[str, tuple[object, ...]]:
    return {
        f"account-{index}": (
            "broker" if index < 2 else "bank",
            "EUR" if index == 0 else "CZK",
            index + 1,
            index + 1 if index < 2 else 0,
            index + 1 if index < 2 else None,
        )
        for index in range(6)
    }


def test_equivalent_six_account_publication_matches_live_boundary() -> None:
    candidate = _six_account_boundary()

    assert _matches_live_publication_boundary(
        baseline_currency_by_user={"user": "CZK"},
        base_currency_by_user={"user": "CZK"},
        candidate_by_user={"user": candidate},
        live_by_user={"user": dict(candidate)},
    )


def test_publication_boundary_rejects_added_account() -> None:
    candidate = _six_account_boundary()
    live = dict(candidate)
    live["account-6"] = ("bank", "CZK", 1, 0, None)

    assert not _matches_live_publication_boundary(
        baseline_currency_by_user={"user": "CZK"},
        base_currency_by_user={"user": "CZK"},
        candidate_by_user={"user": candidate},
        live_by_user={"user": live},
    )


def test_publication_boundary_rejects_changed_revision() -> None:
    candidate = _six_account_boundary()
    live = dict(candidate)
    live["account-0"] = ("broker", "EUR", 2, 2, 2)

    assert not _matches_live_publication_boundary(
        baseline_currency_by_user={"user": "CZK"},
        base_currency_by_user={"user": "CZK"},
        candidate_by_user={"user": candidate},
        live_by_user={"user": live},
    )


def test_publication_boundary_rejects_changed_base_currency() -> None:
    candidate = _six_account_boundary()

    assert not _matches_live_publication_boundary(
        baseline_currency_by_user={"user": "CZK"},
        base_currency_by_user={"user": "EUR"},
        candidate_by_user={"user": candidate},
        live_by_user={"user": dict(candidate)},
    )


def test_publication_boundary_rejects_missing_target_user() -> None:
    candidate = _six_account_boundary()

    assert not _matches_live_publication_boundary(
        baseline_currency_by_user={"user": "CZK", "shared-user": "EUR"},
        base_currency_by_user={"user": "CZK"},
        candidate_by_user={"user": candidate},
        live_by_user={"user": dict(candidate)},
    )


class _ScalarRows:
    def __init__(self, rows: tuple[object, ...]) -> None:
        self._rows = rows

    def all(self) -> tuple[object, ...]:
        return self._rows


class _EquivalentPublicationSession:
    def __init__(
        self,
        *,
        current: object,
        generation: object,
        current_rows: tuple[object, ...],
        candidate_rows: tuple[object, ...],
    ) -> None:
        self.current = current
        self.generation = generation
        self.row_sets = [current_rows, candidate_rows]
        self.get_kwargs: dict[str, object] | None = None

    async def scalar(self, _statement: object) -> object:
        return self.current

    async def get(self, _model: object, _identity: object, **kwargs: object) -> object:
        self.get_kwargs = kwargs
        return self.generation

    async def scalars(self, _statement: object) -> _ScalarRows:
        return _ScalarRows(self.row_sets.pop(0))


def _baseline_account(*, holding_revision: int = 3) -> SimpleNamespace:
    return SimpleNamespace(
        account_id="account",
        account_type="broker",
        account_currency="EUR",
        canonical_revision=4,
        investment_revision=3,
        holding_revision=holding_revision,
        selected_liability_balance_id=None,
    )


@pytest.mark.asyncio
async def test_equivalent_supersession_accepts_exact_published_boundary_without_lock_inversion() -> (
    None
):
    candidate = SimpleNamespace(
        id="candidate", user_id="user", currency="CZK", calculation_version=1
    )
    current = SimpleNamespace(
        id="current",
        user_id="user",
        generation_id="newer-generation",
        currency="CZK",
        calculation_version=1,
    )
    session = _EquivalentPublicationSession(
        current=current,
        generation=SimpleNamespace(state="published", published_at=object()),
        current_rows=(_baseline_account(),),
        candidate_rows=(_baseline_account(),),
    )

    accepted = await _is_equivalent_superseding_publication(
        session,  # type: ignore[arg-type]
        user_id="user",
        candidate=candidate,  # type: ignore[arg-type]
        publication=cast(
            UserReadModelPublicationModel,
            SimpleNamespace(
                user_id="user",
                baseline_id="current",
                generation_id="newer-generation",
                generation_state="published",
                scopes=["portfolio", "dashboard"],
            ),
        ),
        watermark=cast(
            UserReadModelPublicationWatermarkModel,
            SimpleNamespace(
                kind="published",
                generation_id="newer-generation",
            ),
        ),
    )

    assert accepted
    assert session.get_kwargs == {}


@pytest.mark.asyncio
async def test_equivalent_supersession_rejects_different_boundary() -> None:
    candidate = SimpleNamespace(
        id="candidate", user_id="user", currency="CZK", calculation_version=1
    )
    session = _EquivalentPublicationSession(
        current=SimpleNamespace(
            id="current",
            user_id="user",
            generation_id="newer-generation",
            currency="CZK",
            calculation_version=1,
        ),
        generation=SimpleNamespace(state="published", published_at=object()),
        current_rows=(_baseline_account(),),
        candidate_rows=(_baseline_account(holding_revision=2),),
    )

    accepted = await _is_equivalent_superseding_publication(
        session,  # type: ignore[arg-type]
        user_id="user",
        candidate=candidate,  # type: ignore[arg-type]
        publication=cast(
            UserReadModelPublicationModel,
            SimpleNamespace(
                user_id="user",
                baseline_id="current",
                generation_id="newer-generation",
                generation_state="published",
                scopes=["portfolio", "dashboard"],
            ),
        ),
        watermark=cast(
            UserReadModelPublicationWatermarkModel,
            SimpleNamespace(kind="published", generation_id="newer-generation"),
        ),
    )

    assert not accepted


@pytest.mark.asyncio
async def test_equivalent_supersession_rejects_retired_watermark() -> None:
    session = _EquivalentPublicationSession(
        current=object(),
        generation=object(),
        current_rows=(),
        candidate_rows=(),
    )

    accepted = await _is_equivalent_superseding_publication(
        session,  # type: ignore[arg-type]
        user_id="user",
        candidate=SimpleNamespace(user_id="user"),  # type: ignore[arg-type]
        publication=None,
        watermark=cast(
            UserReadModelPublicationWatermarkModel,
            SimpleNamespace(kind="retired", generation_id=None),
        ),
    )

    assert not accepted
    assert session.get_kwargs is None
