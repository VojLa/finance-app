from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass
from io import StringIO

from app.db.models.enums import ImportSource


@dataclass(frozen=True)
class ParsedImportRow:
    row_number: int
    raw_data: dict[str, str | None]
    validation_errors: dict[str, object] | None = None
    error_message: str | None = None


class ImportParseError(Exception):
    pass


def _decode(content: bytes, encoding: str | None) -> str:
    selected = encoding.strip().lower().replace("_", "-") if encoding else "utf-8-sig"
    try:
        return content.decode(selected).removeprefix("\ufeff")
    except (LookupError, UnicodeDecodeError) as exc:
        raise ImportParseError(f"The import file could not be decoded as {selected}.") from exc


def _delimiter(text: str) -> str:
    candidates: list[tuple[int, str]] = []
    for delimiter in (",", ";", "\t"):
        try:
            header = next(csv.reader(StringIO(text, newline=""), delimiter=delimiter, strict=True))
        except (StopIteration, csv.Error):
            continue
        candidates.append((len(header), delimiter))

    if not candidates:
        raise ImportParseError("The import file does not contain a readable CSV header.")
    candidates.sort(reverse=True)
    best_count, best_delimiter = candidates[0]
    if best_count <= 1 or sum(count == best_count for count, _ in candidates) != 1:
        raise ImportParseError("The import file does not use a supported CSV delimiter.")
    return best_delimiter


def _preserve_blank_records(text: str, delimiter: str) -> str:
    lines = text.splitlines(keepends=True)
    if not lines or not lines[0].strip():
        raise ImportParseError("The import file does not contain a valid header row.")
    try:
        header_count = len(next(csv.reader([lines[0]], delimiter=delimiter, strict=True)))
    except csv.Error as exc:
        raise ImportParseError("The import file contains a malformed header row.") from exc

    in_quoted_field = False
    preserved: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        is_physical_blank = not line.rstrip("\r\n")
        if line_number > 1 and is_physical_blank and not in_quoted_field:
            newline = "\r\n" if line.endswith("\r\n") else "\n"
            preserved.append(delimiter * (header_count - 1) + newline)
        else:
            preserved.append(line)
        if line.count('"') % 2:
            in_quoted_field = not in_quoted_field
    return "".join(preserved)


def parse_csv(content: bytes, *, encoding: str | None) -> list[ParsedImportRow]:
    text = _decode(content, encoding)
    if not text.strip():
        raise ImportParseError("The import file is empty.")

    delimiter = _delimiter(text)
    reader = csv.DictReader(
        StringIO(_preserve_blank_records(text, delimiter), newline=""),
        delimiter=delimiter,
        strict=True,
    )
    if not reader.fieldnames or not any((name or "").strip() for name in reader.fieldnames):
        raise ImportParseError("The import file does not contain a valid header row.")

    normalized_headers = [(name or "").strip() for name in reader.fieldnames]
    if any(not name for name in normalized_headers) or len(set(normalized_headers)) != len(
        normalized_headers
    ):
        raise ImportParseError("The import file contains blank or duplicate column names.")
    reader.fieldnames = normalized_headers

    rows: list[ParsedImportRow] = []
    try:
        for raw in reader:
            extra_values = raw.pop(None, None) or []
            normalized = {str(key).strip(): value for key, value in raw.items()}
            for index, value in enumerate(extra_values, start=1):
                normalized[f"__extra_{index}"] = value

            expected = len(normalized_headers)
            actual = expected + len(extra_values) - sum(value is None for value in raw.values())
            is_blank = not any(
                value is not None and (not isinstance(value, str) or bool(value.strip()))
                for value in normalized.values()
            )
            validation_errors: dict[str, object] | None = None
            error_message: str | None = None
            if is_blank:
                validation_errors = {"code": "blank_row"}
                error_message = "The row is blank."
            elif actual != expected:
                validation_errors = {
                    "code": "column_count_mismatch",
                    "expected": expected,
                    "actual": actual,
                }
                error_message = (
                    "The row contains more values than the header defines."
                    if actual > expected
                    else "The row contains fewer values than the header defines."
                )
            rows.append(
                ParsedImportRow(
                    row_number=reader.line_num,
                    raw_data=normalized,
                    validation_errors=validation_errors,
                    error_message=error_message,
                )
            )
    except csv.Error as exc:
        raise ImportParseError("The import file contains malformed CSV data.") from exc

    if not rows:
        raise ImportParseError("The import file does not contain any data rows.")
    return rows


Parser = Callable[..., list[ParsedImportRow]]
PARSER_REGISTRY: dict[ImportSource, Parser] = {
    ImportSource.raiffeisenbank: parse_csv,
    ImportSource.trading212: parse_csv,
    ImportSource.anycoin: parse_csv,
    ImportSource.manual: parse_csv,
}


def parse_import_file(
    source: ImportSource,
    content: bytes,
    *,
    encoding: str | None,
) -> list[ParsedImportRow]:
    try:
        parser = PARSER_REGISTRY[source]
    except KeyError as exc:
        raise ImportParseError("The import source is not supported by the parser.") from exc
    return parser(content, encoding=encoding)
