# Imports Overview

The implemented Python import pipeline safely prepares external CSV data for a
future posting workflow. It does not yet create transactions, investment events,
holdings, or snapshots.

## Batch lifecycle

| Stage | Endpoint action | Result |
| --- | --- | --- |
| Register | `POST /accounts/{account_id}/imports` | A pending batch, unique by user/account/checksum |
| Upload | `PUT /accounts/{account_id}/imports/{batch_id}/file` | Verified raw file in local storage |
| Parse | `POST .../{batch_id}/parse` | Persisted raw rows; batch becomes `processing` |
| Normalize | `POST .../{batch_id}/normalize` | Normalized candidate rows or review issues |

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

There is currently no background queue: parse and normalize run synchronously in
the request. There is also no raw-data retention or purge worker, even though
the database model reserves retention fields.
