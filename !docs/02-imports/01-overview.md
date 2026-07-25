# Imports Overview

The implemented Python import pipeline safely prepares external CSV data and
atomically posts classified batches into canonical history.

## Batch lifecycle

| Stage       | Endpoint action                                      | Result                                                          |
| ----------- | ---------------------------------------------------- | --------------------------------------------------------------- |
| Register    | `POST /accounts/{account_id}/imports`                | A pending batch, unique by user/account/checksum                |
| Upload      | `PUT /accounts/{account_id}/imports/{batch_id}/file` | Verified raw file in local storage                              |
| Parse       | `POST .../{batch_id}/parse`                          | Persisted raw rows; batch becomes `processing`                  |
| Normalize   | `POST .../{batch_id}/normalize`                      | Normalized candidate rows or review issues                      |
| Deduplicate | `POST .../{batch_id}/deduplicate`                    | Unique candidates retained; repeated matches marked `duplicate` |
| Classify    | `POST .../{batch_id}/classify`                       | Persisted deterministic posting intents                         |
| Post        | `POST .../{batch_id}/post`                           | Atomic canonical history and terminal batch counters            |

Registration requires source metadata and a lower-case SHA-256 hexadecimal digest.
The body upload must be `application/octet-stream`; it is streamed, checked
against declared metadata, and is safe to repeat after a successful identical
write. A file may be up to 1 GiB, while synchronous parsing intentionally has a
64 MiB limit.

Parsing keeps every source row. A blank row, malformed column count, or parser
failure is persisted as a failed row rather than silently discarded.
Normalization uses the generic date, amount, currency, external-id, description,
and type shape for bank, manual, and currently Anycoin rows. Trading212 uses a
dedicated schema-version-2 investment-event shape with explicit action
allowlists, Decimal amounts, asset identity, price/total/fee/conversion fields,
and deterministic source-scoped deduplication. Invalid Trading212 rows become
`needs_review`; normalization never posts them.

Duplicate detection is scoped to one account and import source. An already
imported row always wins so canonical history is not rewritten. Otherwise the
earliest eligible row by batch creation time, batch id, source row number, and
row id wins. Every run reconciles all matching pending candidates, including
candidates in other batches that were normalized or deduplicated in a different
order. Failed, cancelled, review, and already duplicate rows cannot become
winners. The operation is repeatable and serialized per account/source in
PostgreSQL. It does not create ledger records.

The imports module also exposes a pure posting-intent classifier for a future
posting stage. It accepts normalized schema version 1, verifies the normalized
source, date, signed decimal amount, and currency, and returns an immutable,
versioned transaction or structured review intent. Successful classification is
limited to Raiffeisenbank and manual rows. Bank/manual rows use only explicit
type tokens and the signed amount fallback; only `internal transfer` and
`interní převod` become internal transfers. Generic `transfer`, `account
transfer`, and `převod` are review issues because they do not prove common
ownership.

Trading212 schema-version-2 rows can produce immutable investment-event posting
intents in 5F-B1. The classifier retains only canonical provider evidence and
does not post or mutate data. Anycoin remains a review issue with
`investment_normalization_required` until its grouped-trade contract exists.
Descriptions and counterparties never determine transfer, refund, loan, or
other financial meaning.

Anycoin now normalizes at batch scope: payment, fill, and refund rows are grouped
by order ID into one schema-version-2 event on a deterministic fill anchor.
Consumed members and neutral/fully-refunded rows are traceable `skipped` markers;
incomplete groups remain review rows. This still creates no ledger records.

Classification persists deterministic posting intents while keeping the batch
in `processing`. Step 5G-A adds an internal transaction-row writer that
revalidates a stored transaction intent, creates exactly one `Transaction`, and
links the imported row without committing or changing batch counters.

Step 5G-B1 adds a pure immutable investment posting-plan builder. It revalidates
the persisted investment intent and produces deterministic event metadata,
conservative asset-resolution evidence, and an ordered movement tuple only when
every numeric and timestamp value is exactly representable by the canonical
database types. Building a plan performs no I/O and creates no `Asset`,
`AssetListing`, `AssetAlias`, `InvestmentEvent`, or `InvestmentMovement`.
Asset/listing resolution belongs to Step 5G-B2 and the investment writer belongs
to Step 5G-B3.

Step 5G-B2 adds the internal conservative asset/listing resolver used by the
future investment writer. It serializes provider-symbol identity and, when
available, ISIN identity with transaction advisory locks; a global symbol alone
is never a merge key. The resolver may create an `Asset` and `AssetListing`
only from sufficient canonical evidence, and creates no alias, event or
movement. Event writing remains Step 5G-B3 and public batch posting remains
Step 5G-C.

Step 5G-B3 adds the internal investment event writer. In its caller-owned
transaction it rebuilds the persisted B1 plan, resolves the optional B2
identity, writes one event with its exact movement set, and links the import row.
Exact replay validates existing history and fails closed on corruption; it never
commits, rolls back, or changes batch counters or status.

Step 5G-C exposes the authenticated batch `post` operation for owner, admin, and
editor roles. The application service locks the batch and its complete,
deterministically ordered row set, validates the whole batch before writing, and
owns one all-or-nothing transaction around the existing transaction and
investment writers. It derives final counters only after every postable row
succeeds, sets `completed_at` once, and finishes as `completed` or
`partially_completed` according to persisted review/failed rows.

A completed batch request is an exact replay, not a shortcut: every imported row
is revalidated against its canonical entity graph while counters, identity
records, and the original `completed_at` remain unchanged. Missing or corrupt
rows, counters, transactions, events, movements, assets, or listings fail
closed without repair. Posting does not update holdings or snapshots and does
not run in a background worker.

There is currently no background queue: parse, normalize, and duplicate
detection run synchronously in the request. There is also no raw-data retention
or purge worker, even though the database model reserves retention fields.
# Import workflow

The persisted pipeline is `register → upload → parse → normalize → deduplicate → classify → post`.
Classification keeps the batch in `processing`: it stores a JSON-safe `normalizedData.posting_intent` only for deduplicated unique rows. A successful intent remains pending; a classifier review retains canonical data, its unique deduplication key, and a safe review intent. Normalization reviews remain data-less. The operation is idempotent and creates no Transaction, InvestmentEvent, movement, holding, or snapshot; posting belongs to Step 5G.
