from __future__ import annotations

from datetime import date
from html import escape


def cnb_xml(
    publication_date: date,
    rows: tuple[tuple[str, str, str], ...] = (("EUR", "1", "24,500"),),
    *,
    extra: str = "",
) -> bytes:
    rendered_rows = "".join(
        (
            f'<radek kod="{escape(currency)}" mena="test" '
            f'mnozstvi="{escape(amount)}" kurz="{escape(rate)}" zeme="Test"/>'
        )
        for currency, amount, rate in rows
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<kurzy banka="CNB" datum="{publication_date:%d.%m.%Y}" poradi="1">'
        f"{extra}"
        '<tabulka typ="XML_TYP_CNB_KURZY_DEVIZOVEHO_TRHU">'
        f"{rendered_rows}</tabulka></kurzy>"
    ).encode()
