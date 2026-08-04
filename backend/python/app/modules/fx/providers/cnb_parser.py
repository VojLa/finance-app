"""Strict parser for the official CNB daily exchange-rate XML document."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

from app.modules.fx.providers.cnb_models import CnbDailyRates, CnbPublishedRate
from app.modules.market_data.models import MarketEvidenceStateError

_DATE_PATTERN = re.compile(r"\d{2}\.\d{2}\.\d{4}\Z")
_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")
_AMOUNT_PATTERN = re.compile(r"[1-9]\d*\Z")
_RATE_PATTERN = re.compile(r"(?:0|[1-9]\d*),\d+\Z")
_EXPECTED_TABLE_TYPE = "XML_TYP_CNB_KURZY_DEVIZOVEHO_TRHU"
_MAX_XML_DEPTH = 3


def _fail() -> MarketEvidenceStateError:
    return MarketEvidenceStateError()


def _depth(element: ElementTree.Element, current: int = 1) -> int:
    return max((_depth(child, current + 1) for child in element), default=current)


def _publication_date(value: object):
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        raise _fail()
    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError as exc:
        raise _fail() from exc


def _decimal(value: object, *, pattern: re.Pattern[str], comma: bool) -> Decimal:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise _fail()
    try:
        result = Decimal(value.replace(",", ".") if comma else value)
    except InvalidOperation as exc:
        raise _fail() from exc
    if not result.is_finite() or result <= 0:
        raise _fail()
    return result


def parse_cnb_daily_rates(body: bytes) -> CnbDailyRates:
    if (
        not isinstance(body, bytes)
        or not body
        or b"<!DOCTYPE" in body.upper()
        or b"<!ENTITY" in body.upper()
    ):
        raise _fail()
    try:
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, UnicodeError, ValueError) as exc:
        raise _fail() from exc
    if root.tag != "kurzy" or root.attrib.get("banka") != "CNB":
        raise _fail()
    publication_date = _publication_date(root.attrib.get("datum"))
    if _depth(root) > _MAX_XML_DEPTH:
        raise _fail()

    tables = [
        child
        for child in root
        if child.tag == "tabulka" and child.attrib.get("typ") == _EXPECTED_TABLE_TYPE
    ]
    if len(tables) != 1:
        raise _fail()

    by_currency: dict[str, CnbPublishedRate] = {}
    for row in tables[0]:
        if row.tag != "radek":
            continue
        if len(row):
            raise _fail()
        currency_code = row.attrib.get("kod")
        if (
            not isinstance(currency_code, str)
            or not _CURRENCY_PATTERN.fullmatch(currency_code)
            or currency_code == "CZK"
            or currency_code in by_currency
        ):
            raise _fail()
        rate = CnbPublishedRate(
            currency_code=currency_code,
            amount=_decimal(row.attrib.get("mnozstvi"), pattern=_AMOUNT_PATTERN, comma=False),
            czk_value=_decimal(row.attrib.get("kurz"), pattern=_RATE_PATTERN, comma=True),
        )
        by_currency[currency_code] = rate
    if not by_currency:
        raise _fail()
    return CnbDailyRates(
        publication_date=publication_date,
        rates=tuple(by_currency[currency] for currency in sorted(by_currency)),
    )
