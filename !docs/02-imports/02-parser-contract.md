# Parser Contract

The current pre-posting import contract has three explicit stages.

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
fields scoped to source and account.

## Stage 3: duplicate detection

Duplicate detection compares normalized candidate keys only inside the same
account and source. Already imported matches are preserved; otherwise the
earliest eligible row wins. Later matches become `duplicate`, including matches
across import batches. Each run reconciles all pending matches for the current
keys, so out-of-order normalization cannot leave two pending winners.
Transaction-level serialization prevents concurrent requests from selecting
different winners. Failed, cancelled, review, and already duplicate rows never
become winners.

New source-specific parsers must be deterministic, preserve enough raw context
for review, and add representative fixture and regression tests. They may not
perform posting or financial calculation in the parser layer.
