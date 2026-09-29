# Step sizing and decomposition

Size measures execution shape, not risk or calendar time. Classify risk separately;
a small high-risk change can require stronger review without becoming a large slice.

| Size | Shape | Default execution |
| --- | --- | --- |
| XS | one mechanical change, usually 1–3 files | direct; focused check |
| S | one clear local behavior, usually 2–6 files | direct or one Luna worker |
| M | one coherent vertical slice, usually 5–12 files | short design; Sol implementation |
| L | several dependent M slices or one unresolved boundary | decompose before implementation |
| XL | cross-domain initiative, migration, or product/architecture epic | dependency and acceptance plan only |

## Complexity score

Add: each application layer +1; public API +1; external provider +2;
schema/migration +3; auth/account isolation +3; money/FX arithmetic +3;
concurrency/background jobs +3; backward compatibility +2; more than ten target
files +2; unresolved decision +3.

- 0–2: XS/S
- 3–5: S/M
- 6–8: M
- 9–12: L
- 13+: XL

The score is a decomposition hint, not automatic model routing. Use
`MODEL-ROUTING.md` for the model decision.

## Mandatory decomposition

Split work when it contains multiple independently observable behaviors, changes
architecture and business behavior together, needs more than one migration
decision, has more than eight independent acceptance criteria, has overlapping
writers, or cannot be reverted as one understandable unit.

Prefer this dependency order: decision → compatible contract → vertical slice →
migration/backfill → integration/security evidence → removal of old path.

## Delegability

A step is delegable only when it has one outcome, exact files or read-only scope,
named authority and invariants, binary criteria, a focused verification command,
and explicit stop conditions. Parallel steps must have no dependency or file overlap.
