"""Canonical persisted identity for one exact Twelve Data quote."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.modules.market_data.models import MarketEvidenceStateError

_SYMBOL = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")
_MIC = re.compile(r"[A-Z0-9]{4}\Z")


def _fail() -> MarketEvidenceStateError:
    return MarketEvidenceStateError()


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _fail()
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class TwelveDataQuoteIdentity:
    symbol: str
    mic_code: str

    @property
    def canonical_external_id(self) -> str:
        return json.dumps(
            {"symbol": self.symbol, "mic_code": self.mic_code},
            ensure_ascii=False,
            separators=(",", ":"),
        )


def parse_twelve_data_quote_identity(value: object) -> TwelveDataQuoteIdentity:
    if not isinstance(value, str) or not value or not value.isascii():
        raise _fail()
    try:
        document = json.loads(value, object_pairs_hook=_strict_object)
    except MarketEvidenceStateError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
        raise _fail() from exc
    if not isinstance(document, dict) or tuple(document) != ("symbol", "mic_code"):
        raise _fail()
    symbol = document.get("symbol")
    mic_code = document.get("mic_code")
    if (
        not isinstance(symbol, str)
        or not _SYMBOL.fullmatch(symbol)
        or not isinstance(mic_code, str)
        or not _MIC.fullmatch(mic_code)
    ):
        raise _fail()
    identity = TwelveDataQuoteIdentity(symbol=symbol, mic_code=mic_code)
    if identity.canonical_external_id != value:
        raise _fail()
    return identity
