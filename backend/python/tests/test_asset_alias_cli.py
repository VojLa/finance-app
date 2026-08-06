from __future__ import annotations

import json

import pytest

from app.modules.asset_aliases.models import AssetAliasConflictError, AssetAliasInvalidError
from scripts import asset_alias


def test_cli_rejects_unsupported_provider_as_safe_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def must_not_load_settings() -> None:
        raise AssertionError

    monkeypatch.setattr(asset_alias, "Settings", must_not_load_settings)
    exit_code = asset_alias.main(
        [
            "list-unresolved",
            "--provider",
            "broker",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert json.loads(captured.err) == {"error": {"code": "asset_alias_invalid"}}


def test_cli_rejects_missing_required_argument_without_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = asset_alias.main(["onboard", "--asset-id", "asset-a"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert json.loads(captured.err)["error"]["code"] == "asset_alias_invalid"


def test_cli_maps_expected_conflict_without_sensitive_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fail(_args: object) -> object:
        raise AssetAliasConflictError()

    monkeypatch.setattr(asset_alias, "_execute", fail)
    exit_code = asset_alias.main(
        [
            "onboard",
            "--asset-id",
            "asset-a",
            "--expected-symbol",
            "BTC",
            "--expected-asset-type",
            "crypto",
            "--expected-currency",
            "EUR",
            "--provider",
            "coingecko",
            "--external-id",
            "bitcoin",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 4
    assert captured.out == ""
    assert "postgresql://" not in captured.err
    assert "Traceback" not in captured.err
    assert json.loads(captured.err) == {"error": {"code": "asset_alias_conflict"}}


def test_cli_has_no_database_url_argument() -> None:
    with pytest.raises(AssetAliasInvalidError):
        asset_alias._parser().parse_args(
            ["list-unresolved", "--provider", "coingecko", "--database-url", "secret"]
        )
