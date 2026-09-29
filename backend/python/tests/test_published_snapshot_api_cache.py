from __future__ import annotations

from app.db.models.enums import AccountType
from app.modules.published_snapshot import api


def test_cache_bounds_entries_and_expires_globally(monkeypatch) -> None:
    now = 100.0
    monkeypatch.setattr(api, "monotonic", lambda: now)
    monkeypatch.setattr(api, "_READ_CACHE_MAX_ENTRIES", 2)
    api._read_cache.clear()
    try:
        keys = tuple(
            api._cache_key(user_id=user, baseline_id="baseline", account_types=None)
            for user in ("a", "b", "c")
        )
        api._cache_result(keys[0], object())  # type: ignore[arg-type]
        api._cache_result(keys[1], object())  # type: ignore[arg-type]
        assert api._cached_result(keys[0]) is not None
        api._cache_result(keys[2], object())  # type: ignore[arg-type]
        assert tuple(api._read_cache) == (keys[0], keys[2])
        assert api._cached_result(keys[1]) is None

        now += api._READ_CACHE_TTL_SECONDS + 0.01
        assert api._cached_result(("absent", "baseline", None)) is None
        assert not api._read_cache
    finally:
        api._read_cache.clear()


def test_cache_key_separates_user_baseline_and_account_type() -> None:
    all_accounts = api._cache_key(user_id="u", baseline_id="b", account_types=None)
    investments = api._cache_key(
        user_id="u", baseline_id="b", account_types=frozenset({AccountType.broker})
    )
    assert (
        len(
            {
                all_accounts,
                investments,
                api._cache_key(user_id="other", baseline_id="b", account_types=None),
                api._cache_key(user_id="u", baseline_id="other", account_types=None),
            }
        )
        == 4
    )
