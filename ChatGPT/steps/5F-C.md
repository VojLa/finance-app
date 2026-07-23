# 5F-C – Persisted batch classification workflow

## Metadata

- Milestone: `0.1 - Architecture Locked`
- Parent: `5F - transaction classification`
- Size: M/L
- Dependency: Step 5F-B2, merged as `0bf5b436c87b3788722cf0969d34017b408a6c00`
- Source of truth: Python `imports` module

## Goal

Add the authenticated, transactional batch workflow that applies the existing pure
`classify_import_row` function to deduplicated import rows and persists its stable,
JSON-safe result under `normalizedData["posting_intent"]`.

This step prepares postable rows for Step 5G. It must not create a `Transaction`,
`InvestmentEvent`, movement, ledger entry, holding, or snapshot.

## Required context

Read before implementation:

- `AGENTS.md`
- `memory/codex_rules.md`
- `ChatGPT/WORKFLOW.md`
- `ChatGPT/steps/5F-A.md`
- `ChatGPT/steps/5F-B1.md`
- `ChatGPT/steps/5F-B2.md`
- `!planning/scope/0.1 - Architecture Locked.md`
- `!planning/architecture/05-domain-model.md`
- `!docs/02-imports/01-overview.md`
- `!docs/02-imports/02-parser-contract.md`
- `backend/python/README.md`
- `backend/python/app/db/models/imports.py`
- `backend/python/app/modules/imports/api.py`
- `backend/python/app/modules/imports/classification.py`
- `backend/python/app/modules/imports/deduplication.py`
- `backend/python/app/modules/imports/normalization.py`
- `backend/python/app/modules/imports/repository.py`

## Current state

The pipeline currently supports:

1. batch registration and upload;
2. parsing into persisted raw rows;
3. source-specific normalization;
4. deterministic account/source deduplication;
5. a pure immutable posting-intent classifier.

The pure classifier already supports:

- Raiffeisenbank and manual schema-v1 transaction intents;
- Trading212 schema-v2 investment-event intents;
- Anycoin schema-v2 grouped trade and standalone transfer intents;
- structured `needs_review` intents.

There is no classification endpoint and the classifier result is not persisted.

## Scope

- Add `POST /api/v1/accounts/{account_id}/imports/{batch_id}/classify`.
- Add an `ImportClassificationService`.
- Add `ImportClassifyResponse`.
- Persist posting intents inside existing `ImportRow.normalizedData` JSONB.
- Add an enforceable deduplication phase marker without a schema migration.
- Preserve duplicate, skipped, parser-failed and earlier review rows.
- Add authorization, locking, state validation, idempotence, rollback and concurrency.
- Add unit, API/OpenAPI and real PostgreSQL integration tests.
- Update import documentation.

## Out of scope

- No Alembic or Prisma migration.
- No new database enum value.
- No new SQLAlchemy column or table.
- No transaction or investment-event insert.
- No ledger posting.
- No movement, asset, listing, category or counterparty resolution.
- No transfer pairing.
- No holdings or snapshot recalculation.
- No background queue.
- No changes to classification financial rules unless required to fix a proven
  persistence-contract defect.
- No unrelated refactoring.

## Endpoint

Add:

```text
POST /api/v1/accounts/{account_id}/imports/{batch_id}/classify
```

Response model:

```text
ImportClassifyResponse
```

Required fields:

```text
batch_id
status
rows_total
rows_classified
rows_needs_review
rows_duplicate
rows_skipped
rows_failed
```

`status` remains `processing`. Step 5G owns final posting and batch completion.

The endpoint has no request body.

## Authorization

Use the established imports write boundary:

```text
owner
admin
editor
```

A viewer must be rejected. Account membership and batch lookup must remain scoped to
the path `account_id`; never trust account information from row JSON.

Authentication and authorization errors must use existing application error contracts.

## Transaction and locking boundary

Classification is one database transaction.

Required order:

1. authorize account write access;
2. fetch the account-scoped batch;
3. require `ImportStatus.processing`;
4. acquire the existing account/source PostgreSQL advisory transaction lock;
5. re-read the batch `FOR UPDATE`;
6. lock all batch rows `FOR UPDATE` in deterministic row-number order;
7. validate the complete workflow boundary before mutating any row;
8. classify eligible rows;
9. update batch counters;
10. commit once.

On any exception, roll back the whole transaction.

Do not commit per row.

## Why a deduplication phase marker is required

Normalization already creates `normalizedData` and a deduplication key. Without an
additional marker, classification cannot distinguish:

- a normalized row that has completed Step 5E; and
- a normalized row for which duplicate detection was skipped.

Calling classification directly after normalization could therefore prepare duplicate
rows for posting.

Step 5F-C must make the phase boundary explicit inside existing JSONB data.

## Reserved workflow metadata

The following top-level keys are reserved by the import workflow:

```text
deduplication
posting_intent
```

Provider normalizers must not emit these keys.

A canonical payload that already contains either reserved key before the corresponding
workflow phase is invalid state and must produce HTTP 409 rather than overwrite data.

### Deduplication marker

After successful duplicate detection, every normalized candidate row in `pending` or
`duplicate` state must contain:

```json
{
  "deduplication": {
    "schema_version": 1,
    "status": "unique"
  }
}
```

or:

```json
{
  "deduplication": {
    "schema_version": 1,
    "status": "duplicate"
  }
}
```

Rules:

- `pending` requires `status = unique`;
- `duplicate` requires `status = duplicate`;
- the marker has no raw data, key, monetary value or provider identifier;
- the marker does not participate in the deduplication key;
- skipped Anycoin markers do not receive this marker;
- failed and normalization-review rows do not receive this marker.

The deduplication endpoint must remain idempotent before classification. It may accept
an absent marker on the first run and an exact valid marker on a repeat run.

The deduplication endpoint must reject a current-batch normalized row that already has
`posting_intent`; phase order cannot move backwards.

When cross-batch reconciliation changes a pending candidate to `duplicate`, update its
deduplication marker to `duplicate`. If that exceptional candidate already contains a
posting intent, remove the posting intent and any classification-review fields before
marking it duplicate so a duplicate can never remain postable.

## Posting-intent persistence

For one eligible unique row:

1. create a canonical classifier input by copying `normalized_data` and removing only
   the reserved workflow metadata keys;
2. call `classify_import_row(source=batch.source, normalized_data=canonical_input)`;
3. serialize with `model_dump(mode="json")`;
4. persist the serialized result under:

```text
normalized_data["posting_intent"]
```

Do not replace the canonical normalized payload. Preserve every provider field,
including Anycoin `order_id` and `asset_direction`.

The stored intent must be JSON-safe and contain no Python `Decimal`, enum or tuple
objects after serialization.

Do not reconstruct the intent manually in the service. The pure classifier remains the
single financial classification authority.

## Successful classification outcome

When the classifier returns target `transaction` or `investment_event`:

- persist the exact serialized posting intent;
- keep row status `pending`;
- preserve the deduplication key;
- preserve the `deduplication.status = unique` marker;
- set `validation_errors = None`;
- set `error_message = None`;
- do not set either created entity ID.

A `pending` row with a valid successful posting intent is ready for Step 5G.

## Classification review outcome

When the classifier returns target `needs_review`:

- persist the exact serialized review intent under `posting_intent`;
- change row status to `needs_review`;
- preserve the canonical normalized payload;
- preserve the deduplication key;
- preserve the `deduplication.status = unique` marker;
- persist the intent error list in `validation_errors` as JSON-safe objects;
- use a bounded generic `error_message`, for example
  `Row requires classification review.`;
- do not echo description, identifier, amount, currency or provider raw data.

This state is distinct from an earlier normalization-review row, which has no canonical
payload and no key.

## Rows that classification must preserve

### Duplicate rows

A valid duplicate row:

- stays `duplicate`;
- retains canonical normalized data;
- retains its deduplication key;
- has `deduplication.status = duplicate`;
- has no `posting_intent`;
- is never passed to the classifier.

### Anycoin skipped markers

Valid schema-v2 Anycoin `group_member`, `fully_refunded_group` and `neutral_row`
markers:

- stay `skipped`;
- retain their marker payload;
- have no deduplication key;
- have no posting intent;
- are never passed to the classifier.

### Parser failures

Parser-failed rows:

- stay `failed`;
- retain their existing safe parser error state;
- have no normalized payload, key or posting intent.

### Earlier normalization review

Rows already in `needs_review` with:

```text
normalized_data = null
deduplication_key = null
```

are preserved and counted. They are not classified.

## Valid classified boundary

The service must recognize both a first successful run and an exact idempotent repeat.

### First-run postable row

```text
status = pending
normalized_data = canonical object
normalized_data.deduplication.status = unique
posting_intent absent
deduplication_key present
created IDs absent
```

### Already classified postable row

```text
status = pending
normalized_data.deduplication.status = unique
posting_intent target = transaction | investment_event
deduplication_key present
created IDs absent
```

### Already classified review row

```text
status = needs_review
canonical normalized data present
normalized_data.deduplication.status = unique
posting_intent target = needs_review
deduplication_key present
created IDs absent
validation_errors equal stored intent errors
```

### Earlier review row

```text
status = needs_review
normalized_data = null
deduplication_key = null
created IDs absent
```

Any other combination is invalid state.

Examples that must be rejected with HTTP 409:

- classify before deduplication marker exists;
- `pending` with duplicate marker;
- `duplicate` with unique marker;
- skipped row with a posting intent;
- pending row without a deduplication key;
- malformed posting intent;
- stored posting intent that differs from a fresh deterministic classification;
- classification review with mismatched `validation_errors`;
- any row with a created Transaction or InvestmentEvent ID;
- imported rows in this pre-posting workflow;
- reserved workflow metadata with unsupported schema version or extra fields.

## Idempotence

Repeating classification after a successful commit must:

- return HTTP 200;
- produce the same response counts;
- perform no semantic row changes;
- preserve byte-equivalent JSON values after database round-trip;
- create no duplicate logs or entities;
- commit safely once, or use a documented no-op commit strategy consistent with the
  other synchronous import services.

For an already classified row, recompute the classifier result from the canonical
payload without workflow metadata and compare it to the stored intent. A mismatch is
corruption or phase drift and must return HTTP 409. Do not silently replace it.

## Concurrency

Two concurrent classify requests for the same batch must serialize and both return the
same final result.

The second request must observe the committed posting intents and follow the idempotent
path. There must be no partial batch, double mutation or lost review state.

Classification and deduplication for the same account/source must use the same advisory
lock namespace so phase transitions cannot interleave.

## Batch counters

After classification:

```text
rows_total = all persisted rows
rows_imported = 0
rows_skipped = duplicate + skipped + failed + needs_review
completed_at = null
status = processing
```

Response counts are derived from final persisted row states and stored intents:

- `rows_classified`: pending rows with valid transaction/investment-event intent;
- `rows_needs_review`: all review rows, including earlier normalization review;
- `rows_duplicate`: duplicate rows;
- `rows_skipped`: skipped marker rows only;
- `rows_failed`: parser-failed rows.

The sum of response categories must equal `rows_total`.

## Errors

Add:

```text
ImportClassifyStateError
code = import_classify_state_invalid
status = 409
```

and:

```text
ImportClassifyRowsMissingError
code = import_classify_rows_missing
status = 409
```

Use the existing account-scoped batch-not-found error.

Error messages must be generic and must not include raw row data, identifiers,
descriptions, counterparties, quantities or monetary values.

## Recommended module structure

Add:

```text
backend/python/app/modules/imports/classification_service.py
```

Keep the existing pure classifier in `classification.py`.

The service module may contain small pure helpers for:

- validating workflow metadata;
- projecting canonical classifier input;
- serializing and validating stored intents;
- classifying row-state boundaries;
- calculating final counters.

Do not place persistence logic inside the pure classifier.

## Repository changes

Reuse:

- account/source advisory lock;
- account-scoped batch fetch;
- batch `FOR UPDATE`;
- deterministic row locks.

Add repository helpers only when they make SQL intent clearer. Do not bypass the
repository with duplicated account-scope queries in the API layer.

## API and OpenAPI tests

Prove:

- endpoint exists at the exact path;
- POST has no request body;
- response references `ImportClassifyResponse`;
- security uses the internal session token contract;
- missing and invalid authentication return existing 401 errors;
- owner, admin and editor can classify;
- viewer is rejected;
- another account cannot classify the batch.

## Unit tests

Add:

```text
backend/python/tests/test_import_classification_service.py
```

Cover at minimum:

- one successful bank/manual transaction intent persistence;
- one successful Trading212 investment intent persistence;
- one successful Anycoin grouped investment intent persistence;
- one successful Anycoin standalone transfer intent persistence;
- classification review transition;
- preservation of duplicate rows;
- preservation of all supported Anycoin skipped markers;
- preservation of parser failures;
- preservation of earlier normalization reviews;
- exact response and batch counters;
- JSON-safe stored values;
- canonical payload remains unchanged outside reserved metadata;
- first run and repeat run equality;
- stored-intent mismatch rejection;
- invalid phase combinations;
- missing rows;
- invalid batch status;
- rollback on commit failure;
- advisory lock, batch lock and row lock use.

Update deduplication unit tests for:

- initial marker creation;
- exact idempotent marker acceptance;
- marker/status mismatch rejection;
- rejection of current-batch posting intents;
- safe cross-batch transition to duplicate.

## PostgreSQL integration tests

Run against a real PostgreSQL database and cover:

1. full manual/Raiffeisenbank normalize → deduplicate → classify persistence;
2. ambiguous bank transfer becomes traceable classification review;
3. Trading212 schema-v2 intent persistence;
4. Anycoin anchor intent persistence while group members remain skipped;
5. Anycoin standalone transfer direction persistence;
6. duplicate rows remain duplicate and receive no posting intent;
7. parser-failed and earlier review rows remain unchanged;
8. classify-before-deduplicate returns 409 with no mutation;
9. repeated classify call is idempotent;
10. concurrent classify calls converge to one result;
11. controlled commit failure rolls back every row and counter;
12. retry after rollback succeeds;
13. viewer rejection and account isolation;
14. zero created `Transaction`, `InvestmentEvent` and movement entities.

The selected PostgreSQL run must report:

```text
0 failed
0 skipped
```

## Documentation

Update the imports overview and parser contract to document:

```text
register → upload → parse → normalize → deduplicate → classify → post (5G)
```

Document:

- deduplication phase metadata;
- persisted posting-intent location;
- successful versus review row state;
- idempotent classification;
- the fact that no ledger entities are created in 5F-C.

## Acceptance criteria

- [ ] Authenticated classify endpoint exists.
- [ ] Owner/admin/editor are allowed and viewer is rejected.
- [ ] Classification requires an explicit successful deduplication marker.
- [ ] Duplicate and skipped rows are never classified.
- [ ] The pure classifier remains the single classification authority.
- [ ] Posting intents are persisted as exact JSON-safe classifier output.
- [ ] Successful rows remain pending for Step 5G.
- [ ] Classification review rows retain canonical data, key and structured review intent.
- [ ] Earlier normalization reviews remain distinguishable and unchanged.
- [ ] Idempotent reruns verify stored intent equality.
- [ ] Invalid or corrupted workflow states return 409 without partial mutation.
- [ ] Advisory locking, row locking, rollback and concurrency are tested.
- [ ] Batch and response counters are deterministic.
- [ ] Real PostgreSQL selection has zero skips and zero failures.
- [ ] No migration, posting or ledger-side work is included.

## Verification

From `backend/python`:

```bash
uv sync --frozen --extra dev

uv run pytest tests/test_import_classification.py
uv run pytest tests/test_import_deduplication.py
uv run pytest tests/test_import_classification_service.py
uv run pytest tests/test_import_normalization.py tests/test_import_classification.py tests/test_import_deduplication.py tests/test_import_classification_service.py

uv run pytest tests/test_import_normalization_integration.py tests/test_import_deduplication_integration.py tests/test_import_classification_integration.py

uv run ruff check .
uv run ruff format --check .
uv run mypy app scripts tests
uv run pytest
uv run python scripts/check.py
```

From repository root:

```bash
npm.cmd test
npm.cmd run lint
npx.cmd tsc --noEmit --incremental false
git diff --check
```

Return the final audit using `ChatGPT/templates/IMPLEMENTATION-OUTPUT.md`.

## Next: 5G – canonical posting

Step 5G will consume only:

- `pending` rows;
- valid `deduplication.status = unique` metadata;
- a validated successful persisted posting intent;
- no created entity IDs.

It will own database entity creation, row `imported` transition, final batch status,
ledger correctness, rollback and posting idempotence.
