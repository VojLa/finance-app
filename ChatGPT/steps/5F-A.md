# 5F-A – Deterministic bank import classification contract

## Metadata

- Milestone: `0.1 - Architecture Locked`
- Parent: `5F - transaction classification`
- Size: M after splitting the original L-sized step
- Dependency: Step 5E, PR #29
- Source of truth: Python `imports` module

## Goal

Add a pure, deterministic and versioned classifier for one valid normalized
import row. Step 5F-A classifies only Raiffeisenbank and manual rows into
transaction posting intents. It must not write to the database or create ledger
records.

## Split

The original 5F combines classification, provider canonicalization, persistence,
API, authorization, concurrency and money semantics. It is split into:

- **5F-A:** shared posting-intent contract, generic payload validation, bank and
  manual classification, review results, unit tests, and composition tests.
- **5F-B:** source-specific Trading212/Anycoin canonicalization and Anycoin
  order grouping, without batch API or ledger posting.
- **5F-C:** authenticated batch classification workflow, persistence, locking,
  idempotence, rollback, concurrency and integration tests.

## Required context

Read:

- `AGENTS.md`
- `memory/codex_rules.md`
- `ChatGPT/WORKFLOW.md`
- `!planning/scope/0.1 - Architecture Locked.md`
- `backend/python/README.md`
- `backend/python/app/db/models/enums.py`
- `backend/python/app/modules/imports/normalizers.py`
- `backend/python/app/modules/imports/deduplication.py`
- `backend/python/tests/test_import_normalization.py`

Legacy TypeScript parsers may be used only as behavior reference.

## Current state

5D stores generic normalized source, date, signed decimal amount, currency and
optional type/description/external ID. 5E leaves unique rows as `pending` and
marks duplicates. That generic shape is sufficient for conservative bank/manual
classification, but it cannot represent a canonical Trading212 investment row
or an Anycoin grouped order.

## Scope

- Add a pure classifier in `backend/python/app/modules/imports/`.
- Define a typed, immutable, serializable and versioned posting-intent result.
- Use `Decimal`; never convert monetary values through `float`.
- Validate untrusted normalized payloads.
- Classify `raiffeisenbank` and `manual` transaction rows only.
- Return structured review errors for ambiguous, unsupported or insufficient
  normalized rows.
- Add focused unit and normalizer-to-classifier composition tests.
- Update import documentation.

## Out of scope

- No FastAPI endpoint.
- No SQLAlchemy repository or database write.
- No row or batch status transition.
- No ledger, transaction, movement, holding or snapshot creation.
- No Prisma/Alembic/schema change.
- No category, counterparty, transfer-pair, FX or asset resolution.
- No description-based financial inference.
- No Trading212/Anycoin canonicalization or successful investment-event
  classification.

## Posting-intent contract

The serialized payload must be stable and versioned so 5F-C can later store it
under `normalizedData["posting_intent"]`.

It supports:

- target `transaction` with `TransactionType` and `TransactionClassification`;
- target `investment_event` with `InvestmentEventType` and optional canonical
  action such as `buy` or `sell`, as a shared future contract only;
- structured `needs_review` errors;
- rejection of unsupported normalized schema versions.

## Deterministic rules

### Raiffeisenbank and manual

1. Normalize optional source type using trim, Unicode case-folding and
   whitespace collapse.
2. Exact supported tokens may select income, expense or an internal transfer.
3. Otherwise use signed `Decimal` amount:
   - positive → `income` + `real_income`;
   - negative → `expense` + `real_expense`;
   - zero → review issue.
4. Produce `internal_transfer` only from `internal transfer` or `interní
převod`.
5. `transfer`, `account transfer` and `převod` are ambiguous and return
   `ambiguous_transfer_type`; they are never automatically internal transfers.
6. Never infer transfer, refund or loan meaning from description or
   counterparty.
7. Do not modify the original signed amount.

### Trading212 and Anycoin

Trading212 and Anycoin always return the structured
`investment_normalization_required` review issue in 5F-A. Step 5D does not
retain the source-specific canonical fields needed for a safe investment intent:

- Trading212 needs asset identity, quantity, price, price currency, total,
  fees, conversion legs and related details.
- Anycoin needs grouping of `trade payment`, `trade fill` and `trade refund`
  rows by order ID before a canonical trade exists.

The classifier must not use generic type or amount data to invent an investment
event. Review messages must not echo raw financial data or identifiers.

## Validation and safety

- Accept normalized schema version `1` only.
- Source argument and normalized source must match.
- Validate required date/currency and finite `Decimal` amount.
- Treat normalized data as untrusted.
- Do not log raw rows, descriptions, identifiers or monetary values.

## Acceptance criteria

- [ ] Pure classifier exists and has no I/O.
- [ ] Output is typed, immutable, serializable and versioned.
- [ ] Raiffeisenbank/manual positive, negative, explicit income, expense and
      unambiguous internal-transfer cases are tested.
- [ ] Generic transfer tokens return `ambiguous_transfer_type` and never become
      `internal_transfer`.
- [ ] Zero amount returns a review issue.
- [ ] Trading212 and Anycoin return `investment_normalization_required`; no
      successful investment intent is created by 5F-A.
- [ ] Composition tests exercise `normalize_import_row` followed by
      `classify_import_row` for all supported and deferred sources.
- [ ] Source mismatch and unsupported schema version are deterministic errors.
- [ ] Tests prove descriptions do not influence financial classification.
- [ ] No `float` conversion is introduced.
- [ ] No API, persistence, schema or unrelated refactor is included.

## Verification

From `backend/python`:

```bash
uv sync --frozen --extra dev
uv run pytest tests/test_import_classification.py
uv run pytest tests/test_import_normalization.py tests/test_import_classification.py
uv run ruff check .
uv run ruff format --check .
uv run mypy app scripts tests
uv run pytest
uv run python scripts/check.py
```

Return results using `ChatGPT/templates/IMPLEMENTATION-OUTPUT.md`.

## Next: 5F-B – source-specific canonicalization

5F-B will add source-specific canonicalization without a batch API or ledger
posting:

- Trading212 canonical investment row;
- Anycoin grouping by order ID;
- asset identity;
- quantity;
- price;
- total amount and currency;
- fees;
- conversion legs;
- representative fixtures.

## Next: 5F-C – batch classification workflow

5F-C will add:

- `POST /api/v1/accounts/{account_id}/imports/{batch_id}/classify`;
- posting-intent persistence;
- account/source advisory lock;
- owner/admin/editor access and viewer rejection;
- duplicate preservation and traceable review rows;
- rollback, idempotence and concurrency handling;
- OpenAPI and PostgreSQL integration tests.
