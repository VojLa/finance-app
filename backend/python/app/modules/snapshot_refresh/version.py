"""Shared calculation-version contract for coordinated snapshots."""

from app.modules.net_worth.manual_service import CURRENT_NET_WORTH_CALCULATION_VERSION
from app.modules.snapshots.manual_service import (
    CURRENT_ACCOUNT_SNAPSHOT_CALCULATION_VERSION,
)

POSTGRESQL_INTEGER_MAX = 2_147_483_647


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
    ):
        raise ValueError("Coordinated snapshot calculation versions do not match.")
    return account_version


def coordinated_snapshot_calculation_version_marker() -> str:
    """Return a deterministic audit marker without choosing a mismatched version."""
    return (
        f"account={CURRENT_ACCOUNT_SNAPSHOT_CALCULATION_VERSION!r};"
        f"net-worth={CURRENT_NET_WORTH_CALCULATION_VERSION!r}"
    )
