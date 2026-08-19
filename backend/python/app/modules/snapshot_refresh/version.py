"""Shared calculation-version contract for coordinated snapshots."""

from app.modules.net_worth.manual_service import CURRENT_NET_WORTH_CALCULATION_VERSION
from app.modules.snapshots.manual_service import (
    CURRENT_ACCOUNT_SNAPSHOT_CALCULATION_VERSION,
)

POSTGRESQL_INTEGER_MAX = 2_147_483_647
CURRENT_COORDINATED_SNAPSHOT_CALCULATION_VERSION = 3
FROZEN_CURRENT_VALUE_BASELINE_CALCULATION_VERSIONS = frozenset({2, 3})


def current_coordinated_snapshot_calculation_version() -> int:
    account_version = CURRENT_ACCOUNT_SNAPSHOT_CALCULATION_VERSION
    net_worth_version = CURRENT_NET_WORTH_CALCULATION_VERSION
    if (
        not isinstance(account_version, int)
        or isinstance(account_version, bool)
        or not isinstance(net_worth_version, int)
        or isinstance(net_worth_version, bool)
        or not 1 <= account_version <= POSTGRESQL_INTEGER_MAX
        or account_version != net_worth_version
        or account_version != CURRENT_COORDINATED_SNAPSHOT_CALCULATION_VERSION
    ):
        raise ValueError("Coordinated snapshot calculation versions do not match.")
    return account_version


def current_value_baseline_calculation_versions(
    *,
    import_fence_active: bool,
) -> frozenset[int]:
    """Return the explicit baseline versions accepted by the current-value reader.

    A current import fence may preserve the last coherent v2 publication while a
    v3 import is not publishable.  Without that fence, only the current coordinated
    version is accepted.  The literal allowlist makes future version changes fail
    closed until this compatibility contract is reviewed deliberately.
    """

    if not isinstance(import_fence_active, bool):
        raise ValueError("Import-fence state must be a boolean.")
    current_version = current_coordinated_snapshot_calculation_version()
    frozen_versions = FROZEN_CURRENT_VALUE_BASELINE_CALCULATION_VERSIONS
    if frozen_versions != frozenset({2, current_version}):
        raise ValueError("Frozen current-value baseline versions are not explicit.")
    if import_fence_active:
        return frozen_versions
    return frozenset({current_version})


def coordinated_snapshot_calculation_version_marker() -> str:
    """Return a deterministic audit marker without choosing a mismatched version."""
    return (
        f"account={CURRENT_ACCOUNT_SNAPSHOT_CALCULATION_VERSION!r};"
        f"net-worth={CURRENT_NET_WORTH_CALCULATION_VERSION!r}"
    )
