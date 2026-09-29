from __future__ import annotations

import pytest

from app.modules.snapshot_refresh.version import (
    CURRENT_COORDINATED_SNAPSHOT_CALCULATION_VERSION,
    FROZEN_CURRENT_VALUE_BASELINE_CALCULATION_VERSIONS,
    current_value_baseline_calculation_versions,
)


def test_current_value_accepts_only_current_version_without_import_fence() -> None:
    assert current_value_baseline_calculation_versions(import_fence_active=False) == frozenset(
        {CURRENT_COORDINATED_SNAPSHOT_CALCULATION_VERSION}
    )


def test_current_value_accepts_explicit_v2_v3_allowlist_with_import_fence() -> None:
    assert FROZEN_CURRENT_VALUE_BASELINE_CALCULATION_VERSIONS == frozenset({2, 3})
    assert current_value_baseline_calculation_versions(import_fence_active=True) == frozenset(
        {2, 3}
    )


def test_current_value_version_policy_rejects_ambiguous_fence_state() -> None:
    with pytest.raises(ValueError, match="Import-fence state must be a boolean"):
        current_value_baseline_calculation_versions(import_fence_active=1)  # type: ignore[arg-type]
