# Supported Sources

| API source value | Current parser                                | Meaning of support                                                                                                         |
| ---------------- | --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `raiffeisenbank` | Source-specific account/card statement parser | Parse exact Czech export shapes, normalize signed Decimal evidence, deduplicate, classify, and post canonical transactions |
| `trading212`     | Generic strict CSV + schema v2 normalizer     | Upload, preserve rows, canonicalize supported investment events, and classify pure intents                                 |
| `anycoin`        | Generic strict CSV                            | Upload, preserve rows, and retain existing grouping/normalization semantics                                                |
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

Browser imports still use the legacy Next.js workflow until 0.1-R4. Trading212,
Anycoin, and manual registry entries retain their existing parser and source
semantics in 0.1-R2. Adding a new source still requires a schema enum decision,
registry entry, deterministic fixtures, and explicit normalization and posting
semantics.
