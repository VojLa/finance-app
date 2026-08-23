# Investments, canonical state, and holdings

## Scope and source of truth

`InvestmentEvent` and its complete `InvestmentMovement` set are canonical
investment history. Account canonical state records committed revisions and
boundaries. Holdings is a derived current projection of active canonical
investment history; it is never the only evidence of what happened.

## Responsibilities and boundaries

- Accept idempotent manual investment commands.
- Write one event and its complete movement set atomically.
- Advance account canonical revision and rebuild Holdings in that transaction.
- Read authorized symbol detail/history without provider calls or finance writes.
- Consume imported canonical investment posting plans.

The backend boundary is `modules/investments/`, `canonical_state/`, and
`holdings/`. Projection work is in `holdings/projection.py`,
`holdings/rebuild_service.py`, and `holdings/repository.py`. Browser manual-add
and symbol adapters use `src/modules/investments/` and
`src/app/api/portfolio/transactions/`.

## Invariants and verification

- A valid command cannot create an empty event.
- An idempotency key binds to one canonical payload: exact replay succeeds,
  different payload reuse conflicts.
- One event plus movements advances canonical lineage exactly once.
- Holdings must represent the exact investment revision it claims; stale or
  ambiguous evidence fails closed for dependent valuation.
- Current/native cost evidence and account/base presentation are distinct; no
  browser-side cost, P/L, or FX reconstruction is allowed.

Tests: `test_manual_investments*`, `test_holding_*`,
`test_canonical_state.py`, `test_empty_investment_holding_revision*`, and
`test_unknown_investment_cost_basis*`. Read the
[cost-basis decision](../../!planning/decisions/0010-multi-currency-holding-cost-basis.md).
