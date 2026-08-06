"""Server-operator CLI for explicit exact provider alias onboarding."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn, TextIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import Settings  # noqa: E402
from app.db.connection import close_database, create_database  # noqa: E402
from app.db.models.enums import AssetAliasProvider, AssetType  # noqa: E402
from app.modules.asset_aliases import (  # noqa: E402
    AssetAliasConflictError,
    AssetAliasDatabaseUnavailableError,
    AssetAliasInvalidError,
    AssetAliasInventoryService,
    AssetAliasNotFoundError,
    AssetAliasOnboardingService,
    AssetAliasStateError,
    OnboardAssetAliasCommand,
    OnboardAssetAliasResult,
    UnresolvedAssetAlias,
)

_ERROR_CODES: tuple[tuple[type[BaseException], str, int], ...] = (
    (AssetAliasInvalidError, "asset_alias_invalid", 2),
    (AssetAliasNotFoundError, "asset_alias_not_found", 3),
    (AssetAliasConflictError, "asset_alias_conflict", 4),
    (AssetAliasStateError, "asset_alias_state_error", 5),
    (AssetAliasDatabaseUnavailableError, "asset_alias_database_unavailable", 6),
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise AssetAliasInvalidError() from None


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    unresolved = subparsers.add_parser("list-unresolved")
    unresolved.add_argument("--provider", required=True)

    onboard = subparsers.add_parser("onboard")
    onboard.add_argument("--asset-id", required=True)
    onboard.add_argument("--expected-symbol", required=True)
    onboard.add_argument("--expected-asset-type", required=True)
    onboard.add_argument("--expected-currency", required=True)
    onboard.add_argument("--expected-isin")
    onboard.add_argument("--provider", required=True)
    onboard.add_argument("--external-id", required=True)
    onboard.add_argument("--dry-run", action="store_true")
    return parser


def _provider(value: object) -> AssetAliasProvider:
    if not isinstance(value, str):
        raise AssetAliasInvalidError()
    try:
        provider = AssetAliasProvider(value)
    except ValueError as exc:
        raise AssetAliasInvalidError() from exc
    if provider not in {
        AssetAliasProvider.coingecko,
        AssetAliasProvider.twelve_data,
    }:
        raise AssetAliasInvalidError()
    return provider


def _asset_type(value: object) -> AssetType:
    if not isinstance(value, str):
        raise AssetAliasInvalidError()
    try:
        return AssetType(value)
    except ValueError as exc:
        raise AssetAliasInvalidError() from exc


def _created_at() -> datetime:
    current = datetime.now(UTC).replace(tzinfo=None)
    return current.replace(microsecond=(current.microsecond // 1_000) * 1_000)


def _result_document(result: OnboardAssetAliasResult) -> dict[str, object]:
    return {
        "aliasId": result.alias_id,
        "assetId": result.asset_id,
        "provider": result.provider.value,
        "externalId": result.external_id,
        "disposition": result.disposition.value,
    }


def _inventory_document(item: UnresolvedAssetAlias) -> dict[str, object]:
    return {
        "assetId": item.asset_id,
        "symbol": item.symbol,
        "assetType": item.asset_type.value,
        "currency": item.currency,
        "isin": item.isin,
        "listings": [
            {
                "listingId": listing.listing_id,
                "provider": (listing.provider.value if listing.provider is not None else None),
                "providerSymbol": listing.provider_symbol,
                "exchange": listing.exchange,
                "currency": listing.currency,
            }
            for listing in item.listings
        ],
    }


async def _execute(args: argparse.Namespace) -> object:
    try:
        settings = Settings()
    except ValueError as exc:
        raise AssetAliasDatabaseUnavailableError() from exc
    database = create_database(settings)
    if database is None:
        raise AssetAliasDatabaseUnavailableError()
    try:
        async with database.session_factory() as session:
            provider = _provider(args.provider)
            if args.command == "list-unresolved":
                unresolved = await AssetAliasInventoryService(session).list_unresolved(provider)
                return [_inventory_document(item) for item in unresolved]
            if args.command != "onboard":
                raise AssetAliasInvalidError()
            onboarded = await AssetAliasOnboardingService(session).onboard(
                OnboardAssetAliasCommand(
                    asset_id=args.asset_id,
                    provider=provider,
                    external_id=args.external_id,
                    expected_symbol=args.expected_symbol,
                    expected_asset_type=_asset_type(args.expected_asset_type),
                    expected_currency=args.expected_currency,
                    expected_isin=args.expected_isin,
                    created_at=_created_at(),
                ),
                dry_run=args.dry_run,
            )
            return _result_document(onboarded)
    finally:
        await close_database(database)


def _write_json(value: object, *, stream: TextIO) -> None:
    print(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        file=stream,
    )


def _error_result(error: BaseException) -> int:
    for error_type, code, exit_code in _ERROR_CODES:
        if isinstance(error, error_type):
            _write_json({"error": {"code": code}}, stream=sys.stderr)
            return exit_code
    _write_json({"error": {"code": "asset_alias_state_error"}}, stream=sys.stderr)
    return 5


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        result = asyncio.run(_execute(args))
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        return _error_result(exc)
    _write_json(result, stream=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
