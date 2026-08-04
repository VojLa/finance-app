from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from support.cnb_fx import cnb_xml

from app.modules.fx.providers.cnb_parser import parse_cnb_daily_rates
from app.modules.market_data.models import MarketEvidenceStateError


def test_parser_returns_exact_canonical_sorted_rates() -> None:
    result = parse_cnb_daily_rates(
        cnb_xml(
            date(2026, 8, 3),
            (("USD", "1", "21,125"), ("EUR", "1", "24,500"), ("JPY", "100", "14,321")),
            extra="<metadata/>",
        )
    )

    assert result.publication_date == date(2026, 8, 3)
    assert result.rates == (
        result.rates[0].__class__("EUR", Decimal("1"), Decimal("24.500")),
        result.rates[0].__class__("JPY", Decimal("100"), Decimal("14.321")),
        result.rates[0].__class__("USD", Decimal("1"), Decimal("21.125")),
    )


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not xml",
        b'<?xml version="1.0"?><other/>',
        b'<kurzy banka="ECB" datum="03.08.2026"><tabulka '
        b'typ="XML_TYP_CNB_KURZY_DEVIZOVEHO_TRHU"/></kurzy>',
        b'<kurzy banka="CNB" datum="2026-08-03"><tabulka '
        b'typ="XML_TYP_CNB_KURZY_DEVIZOVEHO_TRHU"/></kurzy>',
        b'<!DOCTYPE kurzy><kurzy banka="CNB" datum="03.08.2026"/>',
        cnb_xml(date(2026, 8, 3), (), extra="<nested><too><deep/></too></nested>"),
    ],
)
def test_parser_rejects_invalid_document_shape(body: bytes) -> None:
    with pytest.raises(MarketEvidenceStateError):
        parse_cnb_daily_rates(body)


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        ((("EUR", "1", "24,500"), ("EUR", "1", "24,500")), "duplicate currency"),
        ((("eur", "1", "24,500"),), "noncanonical currency"),
        ((("CZK", "1", "1,000"),), "domestic source row"),
        ((("EUR", "0", "24,500"),), "nonpositive amount"),
        ((("EUR", "1.0", "24,500"),), "ambiguous amount locale"),
        ((("EUR", "1", "24.500"),), "ambiguous rate locale"),
        ((("EUR", "1", "0,000"),), "nonpositive rate"),
        ((("EUR", "1", "NaN"),), "nonfinite rate"),
    ],
)
def test_parser_rejects_invalid_rows(
    rows: tuple[tuple[str, str, str], ...],
    reason: str,
) -> None:
    with pytest.raises(MarketEvidenceStateError, match="unavailable"):
        parse_cnb_daily_rates(cnb_xml(date(2026, 8, 3), rows))
    assert reason


def test_parser_rejects_duplicate_or_missing_expected_table() -> None:
    duplicate = (
        b'<kurzy banka="CNB" datum="03.08.2026">'
        b'<tabulka typ="XML_TYP_CNB_KURZY_DEVIZOVEHO_TRHU">'
        b'<radek kod="EUR" mnozstvi="1" kurz="24,500"/></tabulka>'
        b'<tabulka typ="XML_TYP_CNB_KURZY_DEVIZOVEHO_TRHU">'
        b'<radek kod="USD" mnozstvi="1" kurz="21,000"/></tabulka></kurzy>'
    )
    with pytest.raises(MarketEvidenceStateError):
        parse_cnb_daily_rates(duplicate)
    with pytest.raises(MarketEvidenceStateError):
        parse_cnb_daily_rates(
            b'<kurzy banka="CNB" datum="03.08.2026"><tabulka typ="other"/></kurzy>'
        )
