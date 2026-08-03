# Pre-posting Import Contract

The import contract persists every stage so that parsing, normalization,
deduplication, classification, and posting remain explicit and replayable.

## Stage 1: source parser

`parse_import_file` selects a parser from the source registry. Trading212,
Anycoin, and manual retain the generic strict CSV parser. Raiffeisenbank uses a
source-specific parser which detects exactly one supported shape from the
complete trimmed header:

- `account_statement` requires `Datum provedení`, `Zaúčtovaná částka`, and
  `Měna účtu`;
- `card_statement` requires `Datum transakce`, `Zaúčtovaná částka`, and
  `Měna zaúčtování`, with card-specific markers.

Unknown, mixed, or ambiguous Raiffeisenbank headers are fatal without echoing
the complete header or file. The parser supports UTF-8 BOM removal and the
batch's explicit encoding. Shared strict CSV mechanics select one unambiguous
comma, semicolon, or tab delimiter; require non-blank unique headers; preserve
row numbers and raw fields; and persist physical blank or column-mismatch rows
as structured issues. No data row is silently skipped.

Bad encoding, malformed CSV, an empty file, a header-only file, or a fatal
header error fails parsing. Per-row problems remain persisted source evidence.
The parser has no database access and performs no normalization,
classification, deduplication, posting, or financial calculation.

## Stage 2: normalizer

Generic sources use their existing aliases and source semantics. The
Raiffeisenbank normalizer maps the detected account or card statement through
exact Czech source fields and emits schema version 1:

```json
{
  "schema_version": 1,
  "source": "raiffeisenbank",
  "date": "2026-06-14T12:05:00",
  "amount": "-123.45",
  "currency": "CZK",
  "external_id": "provider-or-deterministic-id",
  "description": "deterministic description",
  "counterparty": "optional",
  "type": "odchozí platba"
}
```

Raiffeisenbank dates support the documented Czech date and date-time forms and
remain timezone-naive source evidence. Amounts use `Decimal`, retain the
provider sign, and serialize as finite exact decimal strings. Canonical money
never passes through `float` or `abs`. Currency is exactly three uppercase
ASCII letters.

Descriptions combine an allowlisted source-specific sequence, skip empty
values, and remove exact duplicates. Account counterparties come from `Název
protiúčtu`; card counterparties come from merchant or place evidence. Provider
transaction IDs take precedence. A card row without a stable provider ID uses
a SHA-256 fallback over stable canonical source identity. Filename, batch ID,
upload time, database identity, row number, and randomness are excluded.

## Stage 3: duplicate detection

Duplicate detection compares normalized candidate keys only inside the same
account and source. Already imported matches are preserved; otherwise the
earliest eligible row wins. Later matches become `duplicate`, including
matches across batches. The Raiffeisenbank fallback remains stable when the
same rows are uploaded under a different filename or in another order, while
different accounts retain separate deduplication scopes.

Each run reconciles all pending matches for the current keys. Transaction-level
serialization prevents concurrent requests from selecting different winners.
Failed, cancelled, review, and already duplicate rows never become winners.

## Pure posting-intent classification

`classify_import_row` is deterministic and I/O-free. Schema version 1 produces
either a transaction intent with the original signed `Decimal`,
`TransactionType`, and `TransactionClassification`, or structured
`needs_review` issues that do not echo untrusted source values.

For Raiffeisenbank, incoming payment must have a positive sign; outgoing
payment and card payment must have a negative sign. Missing or unknown types
may use the safe signed-amount fallback. `Převod` is ambiguous and requires
review. `Interní převod` is accepted only as explicit provider evidence. Type
and sign conflicts and zero amounts require review. Description and
counterparty never determine classification.

Trading212 retains its schema-version-2 investment-event contract, including
exact asset, quantity, price, fee, conversion, realized P/L, and provider
identity evidence. Anycoin retains its existing grouping behavior: one
deterministic anchor carries the canonical grouped event and the other group
members remain explicit skipped lineage evidence.

## Workflow metadata and posting

Deduplication adds only `normalizedData.deduplication`; classification stores
`normalizedData.posting_intent`. Provider normalizers create neither key.

The transaction writer locks the classified row, removes workflow metadata from
a copy, re-runs the pure classifier, and requires exact stored-intent equality.
It creates or exactly replays one canonical `Transaction` inside the
caller-owned transaction, including signed amount, source identity,
description, and bounded optional counterparty. It never commits independently.
Persisted corruption fails closed and does not create a replacement
transaction.

Sanitized Raiffeisenbank account and card fixtures prove the complete staged
contract on PostgreSQL. Card transactions do not establish a credit-card
liability balance; liability snapshots require separate explicit liability
evidence.

Committed, synthetic Trading212 and Anycoin fixtures also prove the public
binary-upload-to-read-model path on PostgreSQL. Trading212 creates exact
deposit, buy, and dividend events and movements. Anycoin creates one grouped
buy with an imported anchor plus skipped payment/refund members. Repeated,
renamed, BOM, and reordered inputs preserve account-scoped canonical identity.
Issue fixtures persist every physical row and create no canonical event,
movement, holding, or transaction.

The investment fixture snapshot proof uses a same-currency EUR account and one
explicitly seeded test price for the exact persisted listing. The seeded row is
deterministic test evidence, not a live price provider or provider refresh.
Missing current price evidence fails closed without partial snapshots. No
exchange-rate row, FX provider, buy-price fallback, latest lookup, or
post-refresh account discovery is used.

## Browser transport boundary

The import page sends account identity, one supported source value, and exact
CSV bytes to the same-origin `POST /api/import` route. Next.js authenticates the
session once and then runs the generated Python staged API in order: create,
binary upload, parse, normalize, deduplicate, classify, post, and final batch
read. Each Python request uses a fresh internal token. Multi-file requests are
processed sequentially in their submitted order, with safe partial completion
reported if a later file fails.

No browser or Next.js parser, preview, classifier, posting plan, deduplication
key, holdings calculation, or financial fallback participates in this path.
The checksum is calculated over the exact uploaded bytes, including a UTF-8 BOM
when present. The legacy preview route remains a registered compatibility
surface but is not called by a production page.
