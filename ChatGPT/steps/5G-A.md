# 5G-A – Canonical transaction posting foundation

## Metadata

- Milestone: `0.1 - Architecture Locked`
- Parent: `5G - canonical posting`
- Size: M
- Dependency: Step 5F-C, merged as `16daefcb58314865fb6eedabd4d7b3eb660a56fc`
- Source of truth: persisted import posting intent plus canonical SQLAlchemy models

## Goal

Add the internal transaction-row writer used later by the batch posting endpoint.

For one already locked, valid and classified import row, 5G-A must:

1. validate the complete posting boundary;
2. rebuild the pure classifier result from canonical normalized data;
3. require exact equality with the stored transaction posting intent;
4. create one canonical `TransactionModel`;
5. change the row from `pending` to `imported`;
6. store only `created_transaction_id`;
7. support an exact idempotent replay by validating and returning the existing transaction.

The writer participates in a caller-owned database transaction. It must not commit or
finalize the batch.

## Split context

5G-A handles transaction targets only.

Later substeps own:

- **5G-B:** `InvestmentEvent`, `InvestmentMovement`, asset and listing resolution;
- **5G-C:** authenticated batch endpoint, batch counters, terminal status, advisory lock,
  concurrency and whole-batch rollback.

## Required context

Read before implementation:

- `AGENTS.md`
- `memory/codex_rules.md`
- `ChatGPT/WORKFLOW.md`
- `ChatGPT/steps/5F-A.md`
- `ChatGPT/steps/5F-C.md`
- `ChatGPT/steps/5G.md`
- `!planning/architecture/05-domain-model.md`
- `!docs/02-imports/01-overview.md`
- `backend/python/app/db/models/imports.py`
- `backend/python/app/db/models/transactions.py`
- `backend/python/app/modules/imports/classification.py`
- `backend/python/app/modules/imports/classification_service.py`
- `backend/python/app/modules/imports/repository.py`

Legacy TypeScript ledger code may be inspected only as historical behavior reference. It
is not the source of truth and must not be ported mechanically.

## Scope

Add an internal module, preferably:

```text
backend/python/app/modules/imports/transaction_posting.py
```

It should contain:

- a frozen typed `TransactionPostingPlan`;
- a pure `build_transaction_posting_plan(...)` function;
- a transaction-row writer such as `ImportTransactionPostingWriter`;
- bounded generic posting-state errors;
- small validation helpers.

Small repository helpers may be added when they make the SQL boundary explicit.

Add focused unit tests and real PostgreSQL integration tests.

## Out of scope

- No FastAPI endpoint.
- No batch status or counter update.
- No commit inside the row writer.
- No `InvestmentEvent` or `InvestmentMovement` creation.
- No `Asset`, `AssetListing` or `AssetAlias` creation.
- No holdings or snapshots.
- No category, counterparty, transfer-pair or reporting-currency resolution.
- No migration or schema DDL.
- No change to financial classification rules.
- No background worker.

## Input contract

### First posting

The writer accepts a transaction row only when all fields match:

```text
batch.account_id = requested account
batch.status = processing
row.import_batch_id = batch.id
row.status = pending
row.normalized_data is an object
row.normalized_data.deduplication = {schema_version: 1, status: unique}
row.normalized_data.posting_intent is an object
row.normalized_data.posting_intent.schema_version = 1
row.normalized_data.posting_intent.target = transaction
row.deduplication_key is present
row.validation_errors = null
row.error_message = null
row.created_transaction_id = null
row.created_investment_event_id = null
```

The row and batch are expected to have been locked by the future 5G-C orchestrator. The
writer must not silently issue an independent batch lookup that weakens this contract.

### Exact replay

An exact replay is allowed only when:

```text
row.status = imported
row.created_transaction_id is present
row.created_investment_event_id = null
```

The stored normalized payload, unique marker, posting intent and deduplication key must
still be valid. The referenced transaction must exist and exactly match the canonical
posting plan and import linkage.

Any other combination is invalid state.

## Stored intent validation

Treat `normalized_data` and `posting_intent` as untrusted JSONB.

Before any entity mutation:

1. copy `normalized_data`;
2. remove only `deduplication` and `posting_intent` from the copy;
3. call:

```python
classify_import_row(source=batch.source, normalized_data=canonical_payload)
```

4. serialize using:

```python
model_dump(mode="json")
```

5. require exact equality with the stored posting intent;
6. require target `transaction`;
7. validate the payload through the existing typed `TransactionPostingIntent` model or
   an equivalent discriminated typed boundary.

A mismatch is corruption or phase drift. Do not replace the stored intent.

## Transaction posting plan

`TransactionPostingPlan` must be immutable and must contain only values needed for the
canonical insert and exact replay comparison.

Required fields:

```text
account_id
import_batch_id
source_row_id
date
amount
currency
transaction_type
transaction_classification
description
external_id
```

Use `Decimal`; never convert through `float`.

### Date conversion

`TransactionModel.date` is a naive database timestamp.

Convert the validated posting-intent date deterministically:

- `YYYY-MM-DD` → midnight as a naive `datetime`;
- timezone-aware ISO datetime → convert to UTC and remove timezone information;
- naive ISO datetime → preserve the represented wall-clock value;
- invalid or non-canonical date → posting-state error.

Do not use the current time as transaction date.

### Optional canonical metadata

The posting intent remains the authority for financial fields. The canonical normalized
payload may supply only:

```text
description
external_id
```

Each value must be `null` or a string of at most the normalizer contract limit. Invalid
persisted types or oversized values fail closed.

Do not infer transaction type or classification from description.

## Canonical Transaction mapping

Create `TransactionModel` with:

```text
id = new repository-standard string ID
account_id = batch.account_id
import_batch_id = batch.id
date = plan.date
booking_date = null
amount = plan.amount
currency = plan.currency
reporting_amount = null
reporting_currency = null
type = plan.transaction_type
classification = plan.transaction_classification
description = plan.description
note = null
counterparty = null
external_id = plan.external_id
category_id = null
archived_at = null
deleted_at = null
updated_at = current UTC timestamp stored as naive DB timestamp
```

`is_reviewed` keeps the database default `false` unless the established SQLAlchemy
constructor requires an explicit value.

The new transaction and row linkage must be inserted in the same caller-owned database
transaction.

## First-run row transition

After adding the transaction to the session:

```text
row.status = imported
row.created_transaction_id = transaction.id
row.created_investment_event_id = null
row.validation_errors = null
row.error_message = null
```

Preserve exactly:

- `raw_data`;
- canonical normalized provider data;
- `deduplication` marker;
- `posting_intent`;
- `deduplication_key`;
- `created_at`.

Use no in-place JSONB mutation.

## Transaction ownership

The row writer must:

- add or validate one transaction;
- update one row;
- return the created or existing `TransactionModel`;
- never call `commit()`;
- never call `rollback()` for a caller-owned transaction;
- never update batch counters or status.

The future 5G-C service owns commit and rollback around the whole batch.

## Exact replay comparison

For an imported row, load the referenced transaction and compare all canonical fields:

- transaction ID equals the row reference;
- account ID;
- import batch ID;
- date;
- signed amount;
- currency;
- transaction type;
- transaction classification;
- description;
- external ID;
- booking date is null;
- reporting amount and currency are null;
- note and counterparty are null;
- category is null;
- archived and deleted timestamps are null.

Ignore server-generated `created_at` and the expected mutable bookkeeping timestamp
`updated_at`.

If the entity is missing or differs, raise a generic posting-state error. Never repair or
update canonical history in place.

## Error contract

Add a generic internal application error suitable for the future endpoint, for example:

```text
ImportPostStateError
code = import_post_state_invalid
status = 409
message = The import batch is not available for posting.
```

The message must not include row IDs, raw data, descriptions, external IDs, currencies or
amounts.

The pure builder may raise a bounded internal exception, but the service-facing boundary
must convert invalid persisted state to the generic application error.

## Unit tests

Add:

```text
backend/python/tests/test_import_transaction_posting.py
```

Cover at minimum:

1. manual income plan and model mapping;
2. Raiffeisenbank expense plan and signed amount preservation;
3. explicit internal-transfer type/classification mapping;
4. date-only conversion;
5. timezone-aware datetime conversion to naive UTC;
6. naive datetime preservation;
7. description and external-ID preservation;
8. canonical payload remains unchanged;
9. posting intent is re-derived and compared exactly;
10. stored-intent mismatch rejection;
11. malformed intent rejection;
12. `needs_review` target rejection;
13. `investment_event` target rejection;
14. missing/invalid unique marker rejection;
15. missing deduplication key rejection;
16. pending row with either created ID rejection;
17. pending row with validation errors or error message rejection;
18. duplicate, skipped, failed and needs-review row rejection;
19. imported row without transaction ID rejection;
20. imported row with investment-event ID rejection;
21. exact imported replay returns the existing transaction without `session.add`;
22. referenced transaction missing rejection;
23. referenced transaction field mismatch rejection for each financially relevant field;
24. writer sets only the transaction ID and imported status;
25. writer preserves normalized JSON and deduplication key;
26. writer never commits, rolls back or changes the batch.

Tests should prove that no `float` conversion is used and that input dictionaries are not
mutated.

## PostgreSQL integration tests

Add:

```text
backend/python/tests/test_import_transaction_posting_integration.py
```

Use the repository PostgreSQL fixture and cleanup style.

Cover:

### Manual full preparation

Run at least:

```text
normalize → deduplicate → classify → transaction row writer
```

Commit in the test-owned transaction. Open a new independent session and verify:

- exactly one `Transaction`;
- exact account and import-batch linkage;
- exact signed amount, currency, type and classification;
- exact description and external ID;
- row status `imported`;
- `created_transaction_id` equals the transaction ID;
- `created_investment_event_id` remains null;
- canonical JSON, marker, intent and key are unchanged;
- batch remains `processing` with unchanged counters because 5G-C is not present.

### Raiffeisenbank transaction

Prove one distinct Raiffeisenbank transaction mapping and fresh-session persistence.

### Database idempotence

After the first commit, call the writer again in a new session over the imported row.
Commit and reload again. Verify:

- the same transaction is returned;
- transaction count remains one;
- no canonical field changed;
- row linkage and JSON are unchanged.

### Rollback

Create the transaction and row transition, then force the caller-owned transaction to
roll back before commit. In a new session verify:

- no transaction exists;
- row remains pending;
- created IDs remain null;
- JSON and key are unchanged.

Then perform a clean retry and verify success.

### Corruption

After a valid first post, tamper one canonical transaction field in a controlled test
setup. The replay must return `ImportPostStateError` and must not modify the transaction
or row.

### No investment side effects

All scenarios must leave counts at zero for:

```text
InvestmentEvent
InvestmentMovement
```

The selected PostgreSQL run must report zero failures and zero skips.

## Documentation

Update technical import documentation only enough to state that 5G-A introduces an
internal transaction row writer. The public pipeline still has no `post` endpoint until
5G-C.

Do not claim that batches are finalized or that investment intents are posted.

## Acceptance criteria

- [ ] A frozen typed transaction posting plan exists.
- [ ] Stored intent is treated as untrusted and re-derived before writing.
- [ ] One valid pending transaction row creates exactly one canonical transaction.
- [ ] The row becomes imported and stores only `created_transaction_id`.
- [ ] Canonical JSON and deduplication identity remain unchanged.
- [ ] Exact replay validates and returns the existing transaction.
- [ ] Missing or mismatched existing entity fails closed.
- [ ] The writer performs no commit, rollback or batch finalization.
- [ ] Real PostgreSQL proves persistence, rollback, retry and idempotence.
- [ ] No investment, holding, snapshot or migration work is included.

## Verification

From `backend/python`:

```bash
uv sync --frozen --extra dev
uv run pytest tests/test_import_transaction_posting.py
uv run pytest tests/test_import_transaction_posting_integration.py
uv run ruff check .
uv run ruff format --check .
uv run mypy app scripts tests
uv run pytest
uv run python scripts/check.py
```

Run the integration module with a real PostgreSQL `DATABASE_URL`; it must report:

```text
0 failed
0 skipped
```

From repository root:

```bash
npm.cmd test
npm.cmd run lint
npx.cmd tsc --noEmit --incremental false
git diff --check
```

Return the audit using:

```text
ChatGPT/templates/IMPLEMENTATION-OUTPUT.md
```

## Next: 5G-B – investment event and movement posting

5G-B will define the source-aware asset/listing resolution contract and create canonical
investment events with ordered asset, cash, fee and conversion movements. It will use the
same caller-owned transaction and exact replay principles established by 5G-A.
