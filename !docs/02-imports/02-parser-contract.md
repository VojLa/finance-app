# Pre-posting Import Contract

The current pre-posting import contract has three persisted stages and one pure
classification contract.

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

## Stage 2: normalizer

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

## Pure posting-intent classification

`classify_import_row` is a deterministic, I/O-free contract over one supported
normalized row. It accepts schema version 1 for bank/manual data and schema
version 2 for canonical Trading212 investment data. It returns a frozen,
JSON-serializable posting intent with
its own schema version:

- `transaction` with the original signed `Decimal`, `TransactionType`, and
  `TransactionClassification`;
- `investment_event` with the original signed `Decimal`,
  `InvestmentEventType`, and `buy`/`sell` action for trades as a shared future
  contract;
- `needs_review` with structured field, code, and message entries that do not
  echo untrusted financial or identifying values.

Raiffeisenbank and manual classification normalize only the optional source
type by trimming, Unicode case-folding, and whitespace collapse. Exact income,
expense, and unambiguous internal-transfer tokens take precedence; unsupported
or missing tokens fall back to the signed amount. `transfer`, `account
transfer`, and `převod` are explicitly ambiguous review issues, not internal
transfers. An explicit income/expense token that conflicts with the sign and
every zero amount require review. Description and counterparty values are
ignored.

Trading212 and Anycoin always return `investment_normalization_required` in
5F-A. A Trading212 investment intent needs source-specific asset identity,
quantity, price, total, fee, and conversion data. An Anycoin trade requires
grouping payment, fill, and refund rows by order ID. The current generic
normalized contract contains neither safely, so it cannot create a successful
investment intent. Step 5F-B will add source-specific canonicalization and
grouping; Step 5F-C will add batch persistence and workflow.

This classifier is not yet a persisted batch stage: there is no classification
endpoint, row status transition, database write, or ledger posting.

Trading212 has a dedicated schema-version-2 canonical investment-event shape.
It accepts only exact normalized action tokens and field aliases, uses decimal
strings for all monetary and quantity values, and records invalid rows as
structured review issues. Its fallback duplicate identity excludes note, name,
and raw action spelling; an external ID takes precedence. Schema version 2 is
classified only for Trading212 and produces a frozen intent containing asset,
quantity, money, fee, conversion, realized P/L, provider identity, and the
promotional flag. It still has no posting workflow.

Trading212 provider exports sometimes contain a zero-valued fee column. A zero
fee is treated as absent and is not persisted in the canonical fee section; a
present canonical fee must be strictly positive.

New source-specific parsers must be deterministic, preserve enough raw context
for review, and add representative fixture and regression tests. They may not
perform posting or financial calculation in the parser layer.
