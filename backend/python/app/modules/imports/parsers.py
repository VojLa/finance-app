from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO

from app.db.models.enums import ImportSource


@dataclass(frozen=True)
class ParsedImportRow:
    row_number: int
    raw_data: dict[str, str | None]
    error_message: str | None = None


class ImportParseError(Exception):
    pass


def _decode(content: bytes, encoding: str | None) -> str:
    selected = encoding or "utf-8-sig"
    try:
        return content.decode(selected)
    except (LookupError, UnicodeDecodeError) as exc:
        raise ImportParseError(f"The import file could not be decoded as {selected}.") from exc


def _dialect(text: str) -> csv.Dialect:
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel


def parse_csv(content: bytes, *, encoding: str | None) -> list[ParsedImportRow]:
    text = _decode(content, encoding)
    if not text.strip():
        raise ImportParseError("The import file is empty.")

    reader = csv.DictReader(StringIO(text, newline=""), dialect=_dialect(text))
    if not reader.fieldnames or not any((name or "").strip() for name in reader.fieldnames):
        raise ImportParseError("The import file does not contain a valid header row.")

    normalized_headers = [(name or "").strip() for name in reader.fieldnames]
    if any(not name for name in normalized_headers) or len(set(normalized_headers)) != len(
        normalized_headers
    ):
        raise ImportParseError("The import file contains blank or duplicate column names.")
    reader.fieldnames = normalized_headers

    rows: list[ParsedImportRow] = []
    for row_number, raw in enumerate(reader, start=2):
        extra_values = raw.pop(None, None)
        normalized = {
            str(key).strip(): value.strip() if isinstance(value, str) else value
            for key, value in raw.items()
        }
        is_blank = not any(value not in (None, "") for value in normalized.values())
        error = None
        if extra_values:
            error = "The row contains more values than the header defines."
        elif is_blank:
            error = "The row is blank."
        rows.append(
            ParsedImportRow(
                row_number=row_number,
                raw_data=normalized,
                error_message=error,
            )
        )
    return rows


def parse_import_file(
    source: ImportSource,
    content: bytes,
    *,
    encoding: str | None,
) -> list[ParsedImportRow]:
    parsers = {
        ImportSource.raiffeisenbank: parse_csv,
        ImportSource.trading212: parse_csv,
        ImportSource.anycoin: parse_csv,
        ImportSource.manual: parse_csv,
    }
    return parsers[source](content, encoding=encoding)
