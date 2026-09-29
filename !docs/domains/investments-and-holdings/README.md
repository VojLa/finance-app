# Investments and holdings

Type: domain
Status: current
Owns: investment events, movements, canonical state and Holding projection
Code: `investments/`, `canonical_state/`, `holdings/`, investment adapters
Update when: investment command, lineage or Holding rebuild changes

An `InvestmentEvent` and its complete movements are canonical history. Account canonical state records committed lineage. Holdings are a derived current projection rebuilt with the canonical transaction and never alternate history.

## Capabilities and boundaries

- record account-authorized investment events and their complete movements;
- advance canonical account lineage once per committed command;
- rebuild persisted Holdings as a current derived projection;
- expose manual investment and explicit Holding rebuild entry points;
- treat an externally valued asset transfer as a signed net deposit at its persisted
  event-date market value (incoming positive, outgoing negative);
- resolve unpriced Anycoin BTC transfers from an append-only valuation record that
  references the exact persisted same-day Yahoo BTC-USD price and the latest direct
  as-of Yahoo USD-CZK FX evidence no older than seven days (including the preceding
  business-day observation for weekend transfers),
  without changing the imported movement;
- materialize missing AnyCoin outgoing-trade realized P/L during deterministic
  Holding replay as settlement proceeds minus the disposed average-cost basis;
- preserve unavailable cost basis when evidence is insufficient.

Holdings never replace investment history and browser code never reconstructs them.
The Anycoin transfer valuation overlay is consumed in bulk by Holding rebuild,
account snapshots and portfolio-history replay. Provider access belongs only to the
explicit repair/background path; normal reads and import requests use persisted
evidence only. Incoming transfers establish acquisition basis. Outgoing transfers
reduce the existing basis proportionally and count as a negative external flow, not
as a synthetic sale or realized P/L event.
AnyCoin realized P/L is derived only when the paired trade legs prove quantity,
settlement value/currency and existing average cost. When the disposed cost basis is
unknown, the quantity projection continues and realized P/L remains unavailable; an
already persisted realized P/L without verifiable basis, or a conflicting proven
value, fails closed instead of being silently accepted.

## Navigation

- [Module and layer map](modules.md)
- [Canonical write flow](../../architecture/flows/canonical-write.md)
- [Canonical and money invariants](../../architecture/invariants/README.md)
- [Test matrix](testing.md)
