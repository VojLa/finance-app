# Imports Overview

The implemented Python import pipeline safely prepares external CSV data for a
future posting workflow. It does not yet create transactions, investment events,
holdings, or snapshots.

## Batch lifecycle

| Stage       | Endpoint action                                      | Result                                                          |
| ----------- | ---------------------------------------------------- | --------------------------------------------------------------- |
| Register    | `POST /accounts/{account_id}/imports`                | A pending batch, unique by user/account/checksum                |
| Upload      | `PUT /accounts/{account_id}/imports/{batch_id}/file` | Verified raw file in local storage                              |
| Parse       | `POST .../{batch_id}/parse`                          | Persisted raw rows; batch becomes `processing`                  |
| Normalize   | `POST .../{batch_id}/normalize`                      | Normalized candidate rows or review issues                      |
| Deduplicate | `POST .../{batch_id}/deduplicate`                    | Unique candidates retained; repeated matches marked `duplicate` |

Registration requires source metadata and a lower-case SHA-256 hexadecimal digest.
The body upload must be `application/octet-stream`; it is streamed, checked
against declared metadata, and is safe to repeat after a successful identical
write. A file may be up to 1 GiB, while synchronous parsing intentionally has a
64 MiB limit.

Parsing keeps every source row. A blank row, malformed column count, or parser
failure is persisted as a failed row rather than silently discarded.
Normalization supports a generic date, amount, currency, external-id,
description, and type shape. It records field-specific errors and changes
invalid-but-parsed rows to `needs_review`; it does not discard them or post them.

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
versioned transaction, investment-event, or structured review intent. Bank and
manual rows use only explicit type tokens and the signed amount fallback.
Trading212 and Anycoin rows require an exact allowlisted action. Description and
counterparty text never determine transfer, refund, loan, or other financial
meaning. Trading212 card debits and card costs remain review issues until a
linked cash-transaction contract exists.

Classification currently has no batch endpoint and does not persist its result,
change import status, or create canonical transaction or ledger records.

There is currently no background queue: parse, normalize, and duplicate
detection run synchronously in the request. There is also no raw-data retention
or purge worker, even though the database model reserves retention fields.
