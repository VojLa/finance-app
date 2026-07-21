# Glossary

- **Account currency**: the three-letter main currency configured on an account.
  Account-level aggregate values use it.
- **Account membership**: a user's role and relationship to an account. Roles
  are `owner`, `admin`, `editor`, and `viewer`.
- **Canonical history**: records of what happened, notably transactions and
  investment events. It is not replaced by dashboard aggregates.
- **Holding**: derived position for one account and asset listing, with quantity
  and average buy price.
- **Import batch**: one registered external file, identified by a SHA-256
  checksum within a user/account pair.
- **Import row**: a raw parsed input record with optional normalized data,
  validation errors, status, and a candidate deduplication key.
- **Investment event**: high-level action such as a trade, deposit, withdrawal,
  dividend, currency conversion, or transfer.
- **Movement**: atomic asset, cash, fee, or tax leg belonging to an investment
  event.
- **Listing**: a tradeable representation of an asset, optionally tied to an
  exchange, market identifier, and provider symbol.
- **Native currency**: the currency in which a balance, price, or event occurred;
  it is retained alongside converted aggregates where applicable.
- **Read model**: rebuildable data optimized for reading, such as holdings or
  snapshots.
- **Snapshot**: a stored point-in-time account or net-worth aggregate at a
  defined granularity.
