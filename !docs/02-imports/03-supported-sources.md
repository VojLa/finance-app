# Supported Sources

| API source value | Current parser                                | Meaning of support                                                                                                         |
| ---------------- | --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `raiffeisenbank` | Source-specific account/card statement parser | Parse exact Czech export shapes, normalize signed Decimal evidence, deduplicate, classify, and post canonical transactions |
| `trading212`     | Generic strict CSV + schema v2 normalizer     | Upload through exact read-model E2E for supported deposit, buy, and dividend evidence                                      |
| `anycoin`        | Generic strict CSV + batch grouping           | Upload through exact read-model E2E with deterministic grouped anchor/member lineage                                       |
| `manual`         | Generic strict CSV                            | Upload, preserve rows, and normalize supported manual transactions                                                         |

Raiffeisenbank supports exact `account_statement` and `card_statement` header
contracts. Unknown or mixed shapes fail at file level; malformed data rows are
preserved as reviewable evidence. Account exports use the provider transaction
ID when present. Card exports without one receive a deterministic
account-scoped fallback independent of filename, batch, row number, and row
order.

Amounts remain signed `Decimal` values through canonical transaction posting.
Ambiguous `Převod` rows require review, and card transaction sums are never
treated as liability evidence.

Sanitized fixtures pass the complete pipeline on PostgreSQL. The cash-only CZK
account fixture produces canonical transactions, an exact AccountSnapshot and
NetWorthSnapshot, and matching portfolio/dashboard exact reads without price
or FX providers.

Fully synthetic Trading212 and Anycoin fixtures additionally pass the public
staged API through canonical events, movements, holdings, coordinated
snapshots, and matching portfolio/dashboard exact reads. Their EUR snapshot
tests seed one explicit deterministic test price per exact listing and insert
no exchange rate. This evidence is not a price provider, provider refresh, FX
provider, or completion of R5. Missing price evidence fails closed without a
partial snapshot.

The browser now uses one typed same-origin import transport for
`raiffeisenbank`, `trading212`, and `anycoin`. The Next.js bridge preserves the
exact file bytes and delegates every staged operation to Python; provider
routes are thin compatibility wrappers and own no parser or finance semantics.
Adding a new source still requires a schema enum decision, registry entry,
deterministic fixtures, and explicit normalization and posting semantics.
