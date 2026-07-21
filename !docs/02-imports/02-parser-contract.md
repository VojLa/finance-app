# Parser Contract

The current parser contract has two explicit stages.

## Stage 1: source parser

`parse_import_file` selects a parser from the source registry. All current
sources use the same strict CSV parser, which:

- decodes UTF-8 with BOM removal by default, or uses the batch's explicit encoding;
- accepts exactly one unambiguous delimiter from comma, semicolon, and tab;
- requires non-blank, unique headers;
- preserves physical blank records;
- records each row as raw key/value data and retains row number;
- marks blank or column-count-mismatched rows with a structured parse issue.

A fatal file error—bad encoding, invalid header, ambiguous delimiter, malformed
CSV, or no data rows—fails the batch. Per-row problems must instead be emitted
as rows, never silently skipped.

## Stage 2: generic normalizer

The normalizer looks up common aliases for `date`, `amount`, and `currency`,
with optional `external_id`, `description`, and `type`. It emits this versioned
shape when valid:

```json
{
  "schema_version": 1,
  "source": "trading212",
  "date": "2026-07-21",
  "amount": "123.45",
  "currency": "EUR",
  "external_id": "optional",
  "description": "optional",
  "type": "optional"
}
```

Dates are normalized to ISO date/time values; ambiguous slash dates are rejected.
Amounts are parsed with `Decimal` and serialized as finite decimal strings.
Currency is upper-cased and validated as a 2–20 character source code. The
candidate deduplication key is a SHA-256 hash of stable normalized identity
fields scoped to source and account. It is advisory only: no current code
suppresses rows based on it.

New source-specific parsers must be deterministic, preserve enough raw context
for review, and add representative fixture and regression tests. They may not
perform posting or financial calculation in the parser layer.
