# ADR 0026 – Health-aware listing selection and bounded market-data fallback

Status: Accepted
Date: 2026-09-30
Decision owners: vlastník FinanceApp
Builds on: ADR 0025

## Kontext

ADR 0025 established exact listing-scoped provider identity, native-currency price
evidence and static `AssetListing.basePriority`. It deliberately deferred runtime
health, retry, exchange calendars and fallback. A failed provider request must not
change financial identity, mutate static preference, or cause a similar ticker to
be used as another instrument.

## Rozhodnutí

### Health and concurrency

- Runtime health is stored separately for one exact `(listingId, provider)` identity.
  It records provider symbol, state, last success and attempt, consecutive failures,
  a safe classified reason, retry/cooldown time, state-change time, the last attempt
  token, optimistic version, and a bounded acquisition lease.
  It also retains cumulative successful and failed refresh counters for operational
  reporting; these counters are not price or valuation evidence.
- Health remains scoped to the exact listing/provider identity. Provider-wide
  rate-limit protection is derived from durable cooldowns on those rows and applies
  to every listing using that provider; there is no second guessed aggregate-health
  record that could obscure which identity failed.
- Outcomes are ordered by `(attemptStartedAt, attemptToken)`. Replays are idempotent;
  an older request finishing later cannot replace a newer outcome. Updates use a
  row lock/version check and acquisition uses a persisted lease, so restarts do not
  erase cooldowns and concurrent workers do not create retry storms.
- Success resets failures and returns the state to `healthy`. A first temporary
  timeout/server/incomplete-response failure is `suspect`; a second is `degraded`;
  a third is `unavailable` until its bounded cooldown expires. Rate limits become
  `degraded` with the provider retry time. Unknown symbol, missing provider symbol,
  currency conflict and provider-identity conflict fail closed as `unavailable`
  without ordinary automatic retry. Invalid price and stale timestamp are
  `degraded` and require fresh valid evidence to recover.
- A known closed market is not a provider failure. It advances the attempt metadata,
  preserves the prior usable state and sets the next attempt to the next supported
  session boundary. An unknown calendar remains explicit and is never guessed.
- After a recoverable cooldown expires, an unavailable or degraded listing becomes
  eligible only for a bounded acquisition probe. Valuation continues using a safe
  fallback until a successfully persisted price restores the preferred listing.
- A missing symbol is recorded as a permanent configuration failure only when the
  listing's provider is already explicit. If the provider itself is unknown, the
  listing remains unresolved rather than guessing a provider identity. Adding an
  explicit symbol safely resets that configuration failure for a new probe.

### Deterministic selection and fallback

One application selector receives the requested listing, all candidate listings of
the same Asset, exact provider identities, health, period availability and explicit
FX compatibility evidence. It performs these steps in order:

1. Reject any candidate whose `assetId` or asset type differs, whose native currency
   is unknown, whose provider identity is incomplete, or whose requested period is
   neither already covered by valid evidence nor eligible for a bounded acquisition.
2. Accept the requested currency. A different quote currency is accepted only when
   the caller supplies a direct, fresh FX evidence identity for the valuation target;
   absence of that proof fails closed. The initial production path therefore does
   not infer cross-currency equivalence.
3. Exclude `unavailable` candidates and candidates/provider identities in cooldown.
   `healthy`, `suspect` and `unknown` remain in the preferred tier so one transient
   network error does not immediately force fallback. `degraded` is considered only
   when no preferred-tier candidate is usable.
4. Sort by tier, descending `basePriority`, provider enum value, exact provider
   symbol, MIC (empty last), and listing ID. This explicit tuple is the sole
   tie-breaker; database row order is irrelevant.
5. Return requested listing, selected listing and a safe selection/fallback reason.
   Missing persisted price evidence is reported explicitly rather than being
   disguised as a priority choice.

Fallback is only another listing of the same Asset. Its observation is persisted
under the selected listing and exact provider symbol. Recovery to the higher-priority
listing is automatic after valid evidence restores its health. Yahoo crypto and
CoinGecko may participate only when both identities are explicitly attached to the
same crypto Asset and quote currencies are equal or the explicit FX rule above is
satisfied.

### Retry, calendars and audit

- Temporary failures receive at most two immediate retries with exponential delay
  and bounded jitter. A sanitized provider `Retry-After` header is carried through
  the transport and persisted cooldown; both always win over local delay.
  Permanent identity/configuration failures are not retried automatically.
- Calendar lookup is MIC-based and initially supports XNAS, XNYS, ARCX, XETR, XLON,
  XPRA, XSWX and XTKS. Persisted/test fixtures own holidays and session decisions;
  crypto has no exchange calendar. Other MICs return `unknown_calendar`.
- For a supported closed session, an exact, fresh, identity-matching previous close
  satisfies acquisition planning without an HTTP request. Missing or stale evidence
  is classified `market_closed` only for response completeness/staleness, never to
  hide a timeout, rate limit, server error or identity conflict.
- Health success is finalized after the corresponding price write in the same
  database transaction. The finalization must still own the persisted lease; a
  rejected or taken-over lease rolls back both evidence and health. A writer
  failure therefore cannot create false healthy state, and an expired worker
  cannot publish late evidence after a newer worker completes.
- Manual global alias changes are explicit, account-independent and append an audit
  event containing actor, action, safe before/after identity metadata and timestamp.
  Raw provider payloads, import rows, tokens and financial values are not stored in
  health or audit records.
- Refresh success/failure and fallback are emitted as safe structured operational
  events. The operator health summary reports state counts, unresolved count,
  conflicts, leases/cooldowns and valid-price age without returning price amounts.

## Důsledky

- `basePriority` never changes because of runtime failures.
- Price and FX evidence remain separate; selection cannot perform valuation.
- A fallback cannot rewrite the requested listing or its historical prices.
- Health is operational state, not financial evidence, and deleting/rebuilding it
  cannot alter investment history or existing `PriceSnapshot` citations.
- The selector, state machine and calendars are pure and testable without live APIs;
  repositories only provide persistence, locking and exact candidate evidence.
