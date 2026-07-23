# 5F-A – Deterministic import classification contract

## Metadata

- Milestone: `0.1 - Architecture Locked`
- Parent: `5F - transaction classification`
- Size: M after splitting the original L-sized step
- Dependency: Step 5E, PR #29
- Source of truth: Python `imports` module

## Goal

Add a pure, deterministic and versioned classifier that converts one valid normalized import row into a posting intent for Step 5G. This step must not write to the database or create ledger records.

## Split

The original 5F combines classification, persistence, API, authorization, concurrency and money semantics. It is therefore split according to `ChatGPT/STEP-SIZING.md`:

- **5F-A:** pure classification contract and unit tests.
- **5F-B:** batch endpoint, persistence, locks, rollback, idempotence and integration tests.

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

5D stores normalized source, date, signed decimal amount, currency and optional type/description/external ID. 5E leaves unique rows as `pending` and marks duplicates. Python does not yet decide whether a unique row represents a `Transaction`, an `InvestmentEvent` or a review issue.

## Scope

- Add a pure classifier in `backend/python/app/modules/imports/`.
- Define a typed, immutable and serializable posting-intent result.
- Use `Decimal`; never convert monetary values through `float`.
- Use only explicit normalized source/type/amount fields.
- Return structured review errors for ambiguous or unsupported rows.
- Add focused unit tests and update import documentation.

## Out of scope

- No FastAPI endpoint.
- No SQLAlchemy repository or database write.
- No row or batch status transition.
- No ledger, transaction, movement, holding or snapshot creation.
- No Prisma/Alembic/schema change.
- No category, counterparty, transfer-pair, FX or asset resolution.
- No description-based financial inference.

## Posting-intent contract

The exact Python type may differ, but the serialized payload must be stable and versioned so 5F-B can later store it under `normalizedData["posting_intent"]`.

It must support:

- target `transaction` with `TransactionType` and `TransactionClassification`;
- target `investment_event` with `InvestmentEventType` and optional canonical action such as `buy` or `sell`;
- structured `needs_review` errors;
- rejection of unsupported normalized schema versions.

## Deterministic rules

### Raiffeisenbank and manual

1. Normalize optional source type using trim, Unicode case-folding and whitespace collapse.
2. Exact supported tokens may select income, expense or transfer.
3. Otherwise use signed `Decimal` amount:
   - positive → `income` + `real_income`;
   - negative → `expense` + `real_expense`;
   - zero → review issue.
4. Produce `internal_transfer` only from an explicit transfer token.
5. Never infer transfer/refund/loan meaning from description or counterparty.
6. Do not modify the original signed amount.

### Trading212 and Anycoin

Use an exact allowlist over normalized source type:

- buy/sell variants → `trade`, preserving `buy` or `sell`;
- deposit → `cash_deposit`;
- withdrawal → `cash_withdrawal`;
- dividend variants → `dividend`;
- interest variants → `interest`;
- currency/FX conversion, exchange, convert or swap → `currency_conversion`;
- asset/internal/portfolio transfer → `asset_transfer`;
- fee variants → `fee`;
- staking variants → `staking_reward`;
- airdrop/free-share variants → `airdrop`.

Missing, unknown or contradictory type returns a review issue. Amount sign must not invent an investment event type.

Trading212 card debit/card cost must not silently become a standard investment withdrawal. If the current normalized contract cannot preserve the required linked cash-transaction meaning, return a review issue and document the limitation.

## Validation and safety

- Accept normalized schema version `1` only.
- Source argument and normalized source must match.
- Validate required date/currency and finite `Decimal` amount.
- Treat normalized data as untrusted.
- Do not log raw rows, descriptions, identifiers or monetary values.

## Acceptance criteria

- [ ] Pure classifier exists and has no I/O.
- [ ] Output is typed, immutable, serializable and versioned.
- [ ] RB/manual positive, negative, explicit income, expense and transfer cases are tested.
- [ ] Zero amount returns a review issue.
- [ ] Supported investment action families map to canonical event types.
- [ ] Unknown investment action returns a review issue.
- [ ] Source mismatch and unsupported schema version are deterministic errors.
- [ ] Tests prove descriptions do not influence financial classification.
- [ ] No `float` conversion is introduced.
- [ ] No API, persistence, schema or unrelated refactor is included.

## Verification

From `backend/python`:

```bash
uv run pytest tests/test_import_classification.py
uv run ruff check .
uv run ruff format --check .
uv run mypy app scripts tests
uv run pytest
```

Return results using `ChatGPT/templates/IMPLEMENTATION-OUTPUT.md`.

## Next: 5F-B

5F-B will add `POST /api/v1/accounts/{account_id}/imports/{batch_id}/classify`, persist the intent in `normalizedData`, move ambiguous unique rows to `needs_review`, serialize with the existing account/source advisory lock, preserve duplicates/failures, and add authorization, idempotence, rollback, concurrency, OpenAPI and PostgreSQL integration tests.
