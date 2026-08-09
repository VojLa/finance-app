from datetime import datetime

from scripts.audit_exchange_rates import build_report


def test_build_report_preserves_source_collision_evidence() -> None:
    report = build_report(
        source_rows=[("cnb", 2), ("yahoo_finance", 1)],
        collision_rows=[
            (
                "EUR",
                "CZK",
                datetime(2026, 8, 9),
                ["cnb", "yahoo_finance"],
                2,
            )
        ],
        duplicate_source_identities=0,
        invalid_rows=0,
    )

    assert report.total_rows == 3
    assert [(item.source, item.count) for item in report.source_counts] == [
        ("cnb", 2),
        ("yahoo_finance", 1),
    ]
    assert report.source_collisions[0].from_currency == "EUR"
    assert report.source_collisions[0].to_currency == "CZK"
    assert report.source_collisions[0].observed_at == "2026-08-09T00:00:00"
    assert report.source_collisions[0].sources == ("cnb", "yahoo_finance")
    assert report.duplicate_source_identities == 0
    assert report.invalid_rows == 0
